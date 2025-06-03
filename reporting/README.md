# KVS License Detection Reporting Workflow

This CloudFormation template sets up a comprehensive reporting infrastructure for the KVS License Plate Detection system. It enables data analysis and visualization of license plate detections stored in DynamoDB.

## Overview

The `reporting-workflow.yaml` template creates AWS resources that allow you to:

1. Crawl and catalog license plate detection data from DynamoDB
2. Query the data using Amazon Athena
3. Visualize insights using Amazon QuickSight

## Architecture

![Reporting Workflow Architecture](https://via.placeholder.com/800x400?text=Reporting+Workflow+Architecture)

The solution creates the following components:
- AWS Glue Database and Crawler to catalog DynamoDB data
- Amazon Athena workgroup and configuration for querying
- Amazon S3 buckets for query results and spill location
- IAM roles and policies for secure access between services

## Prerequisites

- An existing DynamoDB table with license plate detection data (created by the main KVS License Detection stack)
- AWS account with permissions to create the resources in this template
- Amazon QuickSight subscription (for visualization)

## Deployment Instructions

### 1. Deploy the CloudFormation Stack

```bash
aws cloudformation create-stack \
  --stack-name kvs-license-reporting \
  --template-body file://reporting-workflow.yaml \
  --parameters ParameterKey=DynamoDBTableName,ParameterValue=LicensePlateDetections \
  --capabilities CAPABILITY_IAM
```

### 2. Configure the Athena DynamoDB Connector

After stack creation completes:

1. Navigate to the Athena console
2. Choose Data sources and catalogs in the navigation pane
3. Click "Create data source"
4. Search for and select "Amazon DynamoDB"
5. Click "Next"
6. Enter "KVSWorkshop" as the Data source name
7. Use the Browse button to select the spill bucket created by this stack
8. Select the acknowledgement check box and click "Create data source"

### 3. Set Up QuickSight

1. Sign up for QuickSight if you haven't already
2. In QuickSight, create a new dataset
3. Choose Athena as the data source
4. Select the KVSWorkshopWorkgroup workgroup
5. Choose the kvsworkshop_db database and the table created by the Glue crawler
6. Create visualizations based on the license plate detection data

### 4. Configure QuickSight Permissions

Add required permissions to the QuickSight service role:

1. Open the IAM console
2. Navigate to Roles and search for "aws-quicksight-service-role-v0"
3. Click "Add permissions" and select "Create inline policy"
4. Select the JSON tab
5. Add the Lambda policy as specified in the CloudFormation outputs
6. Add the S3 policy as specified in the CloudFormation outputs

## Resources Created

| Resource Type | Purpose |
|---------------|---------|
| AWS::S3::Bucket (SpillBucket) | Storage for Athena query spill location |
| AWS::S3::Bucket (AthenaQueryBucket) | Storage for Athena query results |
| AWS::Glue::Database | Database to catalog DynamoDB data |
| AWS::Glue::Crawler | Crawler to discover DynamoDB schema |
| AWS::Athena::WorkGroup | Workgroup for Athena queries |
| AWS::IAM::Role (GlueRole) | IAM role for Glue service |
| AWS::IAM::Role (AthenaRole) | IAM role for Athena service |
| AWS::IAM::Role (QuickSightRole) | IAM role for QuickSight service |

## Query Examples

### Basic Query for License Plate Detections

```sql
SELECT 
  timestamp, 
  license_plate, 
  confidence, 
  camera_id
FROM 
  "kvsworkshop_db"."licenseplatededections"
ORDER BY 
  timestamp DESC
LIMIT 100;
```

### Aggregation Query for Detection Counts

```sql
SELECT 
  license_plate, 
  COUNT(*) as detection_count
FROM 
  "kvsworkshop_db"."licenseplatededections"
GROUP BY 
  license_plate
ORDER BY 
  detection_count DESC
LIMIT 10;
```

## Troubleshooting

1. **Glue Crawler Issues**: Verify that the IAM role has proper permissions to access the DynamoDB table.
2. **Athena Query Failures**: Check that the spill bucket is properly configured and accessible.
3. **QuickSight Connection Problems**: Ensure that the QuickSight service role has the necessary permissions as outlined in the setup instructions.

## Security Considerations

This template implements several security best practices:
- S3 buckets are configured with public access blocks
- IAM roles follow the principle of least privilege
- S3 bucket versioning is enabled for data protection

## Cost Considerations

The following resources in this solution may incur AWS charges:
- AWS Glue Crawler runs (daily by default)
- Amazon Athena queries
- Amazon S3 storage
- Amazon QuickSight subscription

## Related Resources

- [Amazon Athena Documentation](https://docs.aws.amazon.com/athena/)
- [AWS Glue Documentation](https://docs.aws.amazon.com/glue/)
- [Amazon QuickSight Documentation](https://docs.aws.amazon.com/quicksight/)
- [Amazon DynamoDB Documentation](https://docs.aws.amazon.com/dynamodb/)