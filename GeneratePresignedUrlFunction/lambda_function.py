import json
import boto3
import os
import uuid

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ['BUCKET_NAME']

def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        job_id = body.get('job_id', 'UNKNOWN_JOB')
        file_name = body.get('file_name', 'resume.pdf')
        content_type = body.get('content_type', 'application/pdf')

        # Generate a unique candidate ID for this application
        candidate_id = str(uuid.uuid4())
        
        # Create a clean, standardized file path: resumes/REQ-123/uuid-resume.pdf
        object_key = f"resumes/{job_id}/{candidate_id}-{file_name}"

        # Generate the secure upload ticket (valid for 5 minutes)
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': object_key,
                'ContentType': content_type
            },
            ExpiresIn=300
        )

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization"
            },
            "body": json.dumps({
                "upload_url": presigned_url,
                "object_key": object_key,
                "candidate_id": candidate_id
            })
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Failed to generate upload ticket"})
        }