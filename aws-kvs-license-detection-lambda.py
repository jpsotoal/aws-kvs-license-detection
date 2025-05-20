import json
import urllib.parse
import boto3
import logging
import time
import re
from decimal import Decimal 
from botocore.exceptions import ClientError

print('Loading function')

s3 = boto3.client('s3')
rekognition_client = boto3.client('rekognition')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class RekognitionLabel:
    def __init__(self, label, timestamp=None):
        self.name = label.get("Name")
        self.confidence = label.get("Confidence")
        self.instances = label.get("Instances")
        self.parents = label.get("Parents")
        self.timestamp = timestamp

    def to_dict(self):
        rendering = {}
        if self.name is not None:
            rendering["name"] = self.name
        if self.timestamp is not None:
            rendering["timestamp"] = self.timestamp
        return rendering

class RekognitionImage:
    def __init__(self, image, image_name, rekognition_client):
        self.image = image
        self.image_name = image_name
        self.rekognition_client = rekognition_client

    @classmethod
    def from_bucket(cls, s3_object, rekognition_client):
        image = {"S3Object": {"Bucket": s3_object.bucket_name, "Name": s3_object.key}}
        return cls(image, s3_object.key, rekognition_client)

    def detect_labels(self, max_labels):
        try:
            response = self.rekognition_client.detect_labels(
                Image=self.image, MaxLabels=max_labels
            )
            labels = response['Labels']
            print(f'Found {len(labels)} labels in the image:')
            label_names = ''
            for label in labels:
                name = label['Name']
                confidence = label['Confidence']
                if confidence > 95:
                    print(name + "|" + str(confidence))
                    label_names = label_names + name + ","
            
        except ClientError:
            logger.info("Couldn't detect labels in %s.", self.image_name)
            raise
        else:
            return labels
    
    def detect_text(self):
        try:
            response = self.rekognition_client.detect_text(Image=self.image)
            text_detections = response['TextDetections']
            print(f'Found {len(text_detections)} text instances in the image')
            return text_detections
        except ClientError:
            logger.error("Couldn't detect text in %s.", self.image_name)
            raise
    
    def extract_license_plate(self):
        # First detect all text in the image
        text_detections = self.detect_text()
        
        # Look for license plates among detected labels
        labels = self.detect_labels(100)
        has_license_plate = False
        
        for label in labels:
            if label['Name'].lower() in ['license plate', 'vehicle registration plate']:
                has_license_plate = True
                break
        
        # Extract potential license plate text
        license_plate_text = None
        highest_confidence = 0
        
        # If we found a license plate, look for text that might be the plate number
        if has_license_plate:
            for text in text_detections:
                detected_text = text['DetectedText']
                confidence = text['Confidence']
                
                # Check if text length is between 6 and 8 characters
                if (text['Type'] == 'WORD' and 
                    6 <= len(detected_text) <= 8 and
                    # Check if text contains both letters and numbers
                    any(c.isalpha() for c in detected_text) and 
                    any(c.isdigit() for c in detected_text) and
                    # Check if confidence is greater than 90
                    confidence > 90 and
                    confidence > highest_confidence):
                    
                    license_plate_text = detected_text
                    highest_confidence = confidence
                    print(f"Found potential license plate: {detected_text} with confidence {confidence}")
                    print(text)
                    print(license_plate_text)
        
        return {
            'image_name': self.image_name,
            'license_plate_text': license_plate_text,
            'confidence': Decimal(str(highest_confidence)) if highest_confidence else Decimal('0'),
            'has_license_plate': has_license_plate
        }

def ensure_table_exists(dynamodb_client, table_name):
    try:
        dynamodb_client.describe_table(TableName=table_name)
        logger.info(f"Table {table_name} already exists")
    except dynamodb_client.exceptions.ResourceNotFoundException:
        logger.info(f"Creating table {table_name}")
        dynamodb_client.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'image_name', 'KeyType': 'HASH'},  # Partition key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'image_name', 'AttributeType': 'S'},
            ],
            ProvisionedThroughput={'ReadCapacityUnits': 5, 'WriteCapacityUnits': 5}
        )
        # Wait for table creation
        dynamodb_client.get_waiter('table_exists').wait(TableName=table_name)
        logger.info(f"Table {table_name} created successfully")

def convert_floats_to_decimals(obj):
    """Convert all float values in a dictionary to Decimal objects for DynamoDB compatibility"""
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimals(i) for i in obj]
    elif isinstance(obj, float):
        return Decimal(str(obj))
    else:
        return obj

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    # Initialize DynamoDB client
    dynamodb = boto3.resource('dynamodb')
    dynamodb_client = boto3.client('dynamodb')
    table_name = 'LicensePlateDetections'
    
    # Ensure the table exists
    ensure_table_exists(dynamodb_client, table_name)
    table = dynamodb.Table(table_name)
    
    # Get the object from the event
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    image_name = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    
    # Process the image
    s3_object = boto3.resource("s3").Object(bucket_name, image_name)
    rekognition_image = RekognitionImage.from_bucket(s3_object, rekognition_client)
    
    # Extract license plate information
    license_plate_info = rekognition_image.extract_license_plate()
    
    # Add timestamp
    license_plate_info['timestamp'] = int(time.time())
    
    # Store in DynamoDB if a license plate was detected with confidence > 90
    if license_plate_info['license_plate_text'] and license_plate_info['confidence'] > 90:
        try:
            # Already converted confidence to Decimal in extract_license_plate
            table.put_item(Item=license_plate_info)
            logger.info(f"Successfully stored license plate data for {image_name}")
        except Exception as e:
            logger.error(f"Error storing data in DynamoDB: {str(e)}")
    else:
        logger.info(f"No license plate detected with sufficient confidence in {image_name}")
    
    return {
        'headers': {"Content-Type": "image/png"},
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Image processed successfully',
            'license_plate_detected': license_plate_info['license_plate_text'] is not None and license_plate_info['confidence'] > 90,
            'license_plate': license_plate_info.get('license_plate_text', 'None detected'),
            'confidence': float(license_plate_info['confidence']) if license_plate_info['confidence'] else 0
        }, cls=DecimalEncoder),
        'isBase64Encoded': False
    }