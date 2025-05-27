import json
import urllib.parse
import boto3
import logging
import re
import datetime
import os
from decimal import Decimal
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
# Add a handler to ensure logs are formatted properly
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(handler)

logger.info('Lambda function initializing')

s3 = boto3.client('s3')
rekognition_client = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')

# Configure this to match your DynamoDB table name
LICENSE_PLATE_TABLE = os.environ.get('LICENSE_PLATE_TABLE', 'LicensePlateDetections')
# Time window in minutes to consider a license plate as duplicate
DUPLICATE_WINDOW_MINUTES = int(os.environ.get('DUPLICATE_WINDOW_MINUTES', '5'))



class RekognitionImage:
    def __init__(self, image, image_name, rekognition_client):
        self.image = image
        self.image_name = image_name
        self.rekognition_client = rekognition_client

    @classmethod
    def from_bucket(cls, s3_object, rekognition_client):
        image = {"S3Object": {"Bucket": s3_object.bucket_name, "Name": s3_object.key}}
        return cls(image, s3_object.key, rekognition_client)

    def detect_text(self):
        """Detects text in the image"""
        try:
            response = self.rekognition_client.detect_text(Image=self.image)
            text_detections = response['TextDetections']
            logger.info(f'Found {len(text_detections)} text detections in the image')
            return text_detections
        except ClientError as e:
            logger.error(f"Couldn't detect text in {self.image_name}. {e}")
            raise

def process_license_plate(text_detections):
    """
    Process text detections to find and clean license plate text
    Returns a tuple of (license_plate, confidence)
    """
    # First, look for text detections with high confidence
    potential_plates = []
    
    for detection in text_detections:
        if detection['Type'] == 'LINE':  # Focus on LINE detections which are complete text lines
            text = detection['DetectedText']
            confidence = detection['Confidence']
            
            # Apply license plate pattern matching - adjust regex for your specific format
            # This example looks for patterns like: ABC123, ABC-123, ABC 123, etc.
            cleaned_text = re.sub(r'\s+', '', text)  # Remove spaces
            
            # Check if the text matches common license plate patterns
            # Adjust these patterns based on your specific license plate formats
            if re.match(r'^[A-Z0-9]{5,8}$', cleaned_text) or re.match(r'^[A-Z]{1,3}[-\s]?[0-9]{1,4}$', text):
                potential_plates.append((text, cleaned_text, confidence))
    
    # Sort by confidence and return the highest confidence match
    if potential_plates:
        potential_plates.sort(key=lambda x: x[2], reverse=True)
        original_text, cleaned_text, confidence = potential_plates[0]
        logger.info(f"Detected license plate: {original_text} (cleaned: {cleaned_text}) with confidence {confidence:.2f}")
        return cleaned_text, confidence
    
    return None, 0

def check_duplicate_license_plate(license_plate, time_window_minutes=None):
    """Check if this license plate was recently detected within the time window"""
    try:
        table = dynamodb.Table(LICENSE_PLATE_TABLE)
        
        # Calculate the timestamp threshold (current time minus window)
        if time_window_minutes is None:
            time_window_minutes = DUPLICATE_WINDOW_MINUTES
        current_time = datetime.datetime.now()
        time_threshold = (current_time - datetime.timedelta(minutes=time_window_minutes)).isoformat()
        
        # Query for recent entries with this license plate
        response = table.scan(
            FilterExpression="LicensePlate = :lp AND #ts > :time",
            ExpressionAttributeNames={
                "#ts": "Timestamp"
            },
            ExpressionAttributeValues={
                ":lp": license_plate,
                ":time": time_threshold
            }
        )
        
        items = response.get('Items', [])
        if items:
            logger.info(f"Found duplicate license plate {license_plate} within the last {time_window_minutes} minutes")
            return True
        
        return False
    except ClientError as e:
        logger.error(f"Error checking for duplicate license plate: {e}")
        # If there's an error checking, we'll proceed with saving
        return False

def save_to_dynamodb(license_plate, confidence, image_key, bucket_name):
    """Save the license plate detection to DynamoDB"""
    try:
        # Check for duplicates first
        is_duplicate = check_duplicate_license_plate(license_plate)
        if is_duplicate:
            logger.info(f"Skipping duplicate license plate: {license_plate}")
            return False
            
        table = dynamodb.Table(LICENSE_PLATE_TABLE)
        timestamp = datetime.datetime.now().isoformat()
        
        item = {
            'image_name': image_key,  # Primary key required by the table
            'LicensePlate': license_plate,
            'Timestamp': timestamp,
            'Confidence': Decimal(str(confidence)),  # Convert float to Decimal
            'ImageKey': image_key,
            'BucketName': bucket_name
        }
        
        table.put_item(Item=item)
        logger.info(f"Saved license plate {license_plate} to DynamoDB")
        return True
    except ClientError as e:
        logger.error(f"Error saving to DynamoDB: {e}")
        return False

def lambda_handler(event, context):
    # Get the object from the event
    bucket_name = event['Records'][0]['s3']['bucket']['name']
    image_key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    
    # Enhanced logging with request ID for traceability
    request_id = context.aws_request_id
    logger.info(f"[RequestID: {request_id}] Processing image {image_key} from bucket {bucket_name}")
    
    try:
        # Create S3 object and Rekognition image
        s3_object = boto3.resource("s3").Object(bucket_name, image_key)
        rekognition_image = RekognitionImage.from_bucket(s3_object, rekognition_client)
        
        # Detect text in the image
        logger.info(f"[RequestID: {request_id}] Calling Rekognition to detect text")
        text_detections = rekognition_image.detect_text()
        
        # Process the text to find license plates
        license_plate, confidence = process_license_plate(text_detections)
        
        if license_plate:
            logger.info(f"[RequestID: {request_id}] License plate detected: {license_plate} with confidence {confidence:.2f}")
            
            # Save the detection to DynamoDB (if not a duplicate)
            saved = save_to_dynamodb(license_plate, confidence, image_key, bucket_name)
            
            result = {
                'license_plate': license_plate,
                'confidence': float(confidence),
                'image_key': image_key,
                'saved_to_db': saved
            }
            
            if not saved:
                result['duplicate'] = True
                logger.info(f"[RequestID: {request_id}] Duplicate license plate - not saved to DynamoDB")
            
            return {
                'statusCode': 200,
                'body': json.dumps(result, default=str)
            }
        else:
            logger.info(f"[RequestID: {request_id}] No license plate detected in the image")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No license plate detected',
                    'image_key': image_key
                }, default=str)
            }
            
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': f'Error processing image: {str(e)}',
                'image_key': image_key
            }, default=str)
        }
