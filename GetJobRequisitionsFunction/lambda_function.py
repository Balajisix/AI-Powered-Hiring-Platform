import json
import boto3
from decimal import Decimal
from collections import defaultdict

dynamodb = boto3.resource('dynamodb')
jobs_table = dynamodb.Table('JobRequisitionsTable')
candidates_table = dynamodb.Table('CandidatesTable')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    try:
        # 1. Fetch all jobs
        jobs = jobs_table.scan().get('Items', [])

        # 2. Fetch all candidates and count per job_id
        candidates = candidates_table.scan().get('Items', [])
        
        total_count = defaultdict(int)      # all candidates per job
        ai_screened_count = defaultdict(int) # candidates with ai_score > 0

        for c in candidates:
            job_id = c.get('job_id')
            if not job_id:
                continue
            total_count[job_id] += 1
            # ai screened = resume was evaluated by Bedrock (has a real score)
            if c.get('ai_score', 0) and c.get('application_status') != 'Evaluating...':
                ai_screened_count[job_id] += 1

        # 3. Inject live counts into each job
        for job in jobs:
            job_id = job.get('id')
            job['candidatesCount'] = total_count.get(job_id, 0)
            job['aiScreenedCount'] = ai_screened_count.get(job_id, 0)

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET"
            },
            "body": json.dumps(jobs, cls=DecimalEncoder)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Failed to fetch job requisitions"})
        }