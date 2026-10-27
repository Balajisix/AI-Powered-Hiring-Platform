import json
import boto3
import uuid
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('JobRequisitionsTable') 

def lambda_handler(event, context):
    try:
        body = event.get('body')

        if isinstance(body, str):
            body = json.loads(body)
        elif body is None:
            body = {}
        
        title = body.get('title')
        department = body.get('department')
        location = body.get('location', 'Remote')
        job_type = body.get('type', 'Full-time')
        job_description = body.get('job_description', '')

        print("Body: ", body)
        
        if not title or not department:
            return {
                "statusCode": 400,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "Title and Department are required."})
            }

        job_id = f"REQ-{str(uuid.uuid4())[:8].upper()}"
        posted_date = datetime.now().strftime("%b %d, %Y")

        new_job = {
            'id': job_id,
            'title': title,
            'department': department,
            'location': location,
            'type': job_type,
            'job_description': job_description,
            'status': 'Active',
            'candidatesCount': 0,
            'aiScreenedCount': 0,
            'postedDate': posted_date
        }

        # Save to DynamoDB
        table.put_item(Item=new_job)

        return {
            "statusCode": 201,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization"
            },
            "body": json.dumps(new_job)
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Failed to create job requisition"})
        }