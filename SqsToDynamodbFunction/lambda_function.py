import json
import boto3
import os
import uuid

dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ.get('TABLE_NAME')
table = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            payload = json.loads(record['body'])
            
            candidate_id = payload.get('candidate_id', str(uuid.uuid4()))
            
            item = {
                'candidate_id': candidate_id,
                'candidate_name': payload.get('candidate_name', 'Unknown'),
                'candidate_email': payload.get('candidate_email', 'Unknown'),
                'resume_s3_key': payload.get('s3_object_key', 'Not Uploaded'),
                'job_id': payload.get('job_id', 'Unknown'),
                'role_applied': payload.get('role_applied', 'General Application'),
                'application_status': 'Pending HR',
                'interview_score': 0
            }
            
            table.put_item(Item=item)
            print(f"Successfully saved candidate {candidate_id} to database.")
            
        except Exception as e:
            print(f"Error processing record: {str(e)}")
            
    return {
        'statusCode': 200,
        'body': json.dumps('SQS Batch processed successfully')
    }