# KVS License Plate Detection Demo

This project demonstrates an automated license plate detection system using AWS Kinesis Video Streams (KVS), Amazon Rekognition, Lambda, S3, and DynamoDB.

## Architecture Overview

1. **EC2 Instance**: Runs the KVS producer SDK to stream video
2. **Kinesis Video Stream**: Captures and processes video data
3. **S3 Bucket**: Stores image frames extracted from the video stream
4. **Lambda Function**: Processes images to detect license plates using Rekognition
5. **DynamoDB**: Stores detected license plate information

## Prerequisites

- AWS CLI installed and configured with appropriate permissions
- An AWS account with access to create the required resources

## Deployment Instructions

### 1. Deploy the CloudFormation Stack

```bash
aws cloudformation create-stack \
  --stack-name kvs-license-detection \
  --template-body file://test.yaml \
  --capabilities CAPABILITY_IAM
```

### 2. Monitor Stack Creation

```bash
aws cloudformation describe-stacks \
  --stack-name kvs-license-detection
```

### 3. Access EC2 Instance

Once the stack is created successfully, retrieve the SSH key:

```bash
aws ec2 describe-key-pairs \
  --key-names aws-kvs-license-detection-key \
  --query 'KeyPairs[0].KeyMaterial' \
  --output text > aws-kvs-license-detection-key.pem

chmod 400 aws-kvs-license-detection-key.pem
```

Connect to the EC2 instance:

```bash
ssh -i aws-kvs-license-detection-key.pem ubuntu@<EC2-PUBLIC-IP>
```

Replace `<EC2-PUBLIC-IP>` with the public IP address from the CloudFormation outputs.

## Testing the Solution

### 1. Stream Video to KVS

On the EC2 instance, use the pre-installed GStreamer with KVS plugin:

```bash
export GST_PLUGIN_PATH=/home/ubuntu/amazon-kinesis-video-streams-producer-sdk-cpp/build
export AWS_DEFAULT_REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)

gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert ! video/x-raw,format=I420,width=1280,height=720 ! \
  x264enc bframes=0 key-int-max=45 bitrate=500 ! \
  h264parse ! kvssink stream-name=aws-kvs-license-detection-demo storage-size=512
```

### 2. View Results

1. Check the S3 bucket for extracted frames:
   ```bash
   aws s3 ls s3://aws-kvs-license-detection-s3-$(aws sts get-caller-identity --query 'Account' --output text)-$(aws configure get region)
   ```

2. Query DynamoDB for detected license plates:
   ```bash
   aws dynamodb scan --table-name LicensePlateDetections
   ```

## How It Works

1. The EC2 instance streams video to Kinesis Video Stream
2. KVS extracts image frames at 5-second intervals and saves them to S3
3. S3 triggers the Lambda function when new images are uploaded
4. Lambda uses Rekognition to detect license plates in the images
5. If a license plate is detected with high confidence, the information is stored in DynamoDB

## Cleanup

To delete all resources created by this stack:

```bash
aws cloudformation delete-stack --stack-name kvs-license-detection
```

## Troubleshooting

- **EC2 Connection Issues**: Ensure your security group allows SSH access from your IP
- **KVS Streaming Issues**: Check EC2 instance logs and ensure IAM permissions are correct
- **Lambda Errors**: Check CloudWatch Logs for the Lambda function
- **Missing License Plate Detections**: Ensure images contain clear, visible license plates for Rekognition to detect