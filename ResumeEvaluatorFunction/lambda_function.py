import json
import boto3
import os
import re

# Initialize clients
s3 = boto3.client('s3')
bedrock = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')
sfn = boto3.client('stepfunctions')

candidates_table = dynamodb.Table(os.environ['CANDIDATES_TABLE'])
jobs_table = dynamodb.Table(os.environ['JOBS_TABLE'])
BUCKET_NAME = os.environ['BUCKET_NAME']
STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']


def lambda_handler(event, context):
    for record in event['Records']: 
        try:
            payload = json.loads(record['body'])

            job_id = payload['job_id']
            candidate_id = payload['candidate_id']
            candidate_name = payload.get('candidate_name', 'Unknown')
            candidate_email = payload.get('candidate_email', 'Unknown')
            s3_object_key = payload.get('s3_object_key', '')
            role_applied_from_payload = payload.get('role_applied', 'General Application')

            print(f"Processing application for {candidate_name} (Job: {job_id})")

            candidates_table.put_item(Item={
                'candidate_id': candidate_id,
                'candidate_name': candidate_name,
                'candidate_email': candidate_email,
                'job_id': job_id,
                'role_applied': role_applied_from_payload,
                'resume_s3_key': s3_object_key,
                'application_status': 'Evaluating...',
                'ai_score': 0,
                'interview_score': 0,
                'interview_date': '-'
            })
            print(f"Initial record saved for {candidate_name}.")

            # STEP 2: Fetch Job Description from DynamoDB
            job_response = jobs_table.get_item(Key={'id': job_id})
            if 'Item' not in job_response:
                raise Exception(f"Job {job_id} not found in database.")

            jd_text = job_response['Item'].get('job_description', 'No description provided.')
            role_applied = job_response['Item'].get('title', role_applied_from_payload)

            # STEP 3: Fetch PDF from S3
            print(f"Downloading resume {s3_object_key} from {BUCKET_NAME}...")
            s3_response = s3.get_object(Bucket=BUCKET_NAME, Key=s3_object_key)
            pdf_bytes = s3_response['Body'].read()
            print(f"PDF size: {len(pdf_bytes)} bytes, header: {pdf_bytes[:5]}")

            if not pdf_bytes.startswith(b'%PDF-'):
                raise Exception(f"Invalid PDF: {s3_object_key}")

            # STEP 4: Build prompt
            prompt = f"""
You are an expert ATS system. Carefully read the attached resume PDF and evaluate it against this Job Description:

'{jd_text}'

Instructions:
- Read the candidate's actual skills, experience, and education from the resume
- Compare them against the JD requirements
- Be generous: partial matches still count

Return ONLY a raw JSON object with no markdown, no extra text:
{{"score": <0-100>, "status": "<Proceed or Rejected>"}}

Rule: "status" must be "Proceed" if score >= 70, else "Rejected".
"""

            # STEP 5: Call Bedrock
            print("Evaluating candidate with Nova Pro...")
            bedrock_response = bedrock.converse(
                modelId="amazon.nova-pro-v1:0",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "document": {
                                    "name": "resume",
                                    "format": "pdf",
                                    "source": {"bytes": pdf_bytes}
                                }
                            },
                            {"text": prompt}
                        ]
                    }
                ],
                inferenceConfig={"temperature": 0.1}
            )

            # STEP 6: Parse response
            raw_text = bedrock_response['output']['message']['content'][0]['text']
            print(f"Raw model response: {raw_text}")

            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                evaluation = json.loads(json_match.group())
            else:
                raise Exception(f"Could not extract JSON from model response: {raw_text}")

            print(f"Evaluation result: score={evaluation['score']}, status={evaluation['status']}")
            resume_decision = "PROCEED" if evaluation['score'] >= 70 else "REJECTED"

            if resume_decision == "PROCEED":
                application_status = "RESUME SHORTLISTED"
            else:
                application_status = "RESUME REJECTED"

            candidates_table.put_item(Item={
                'candidate_id': candidate_id,
                'candidate_name': candidate_name,
                'candidate_email': candidate_email,
                'job_id': job_id,
                'role_applied': role_applied,
                'resume_s3_key': s3_object_key,
                'ai_score': evaluation['score'],
                'resume_decision': resume_decision,
                'application_status': application_status,
                'interview_score': 0,
                'interview_date': '-'
            })
            print(f"Final record saved for {candidate_name} with score {evaluation['score']}.")

            # STEP 8: Trigger Step Functions email workflow
            sfn.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({
                    "candidate_id": candidate_id,
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    "status": evaluation['status']
                })
            )

            print(f"Successfully processed {candidate_name}.")

        except Exception as e:
            print(f"Error processing candidate: {str(e)}")
            # Update status to Error so it's visible in dashboard
            try:
                candidates_table.update_item(
                    Key={'candidate_id': candidate_id},
                    UpdateExpression="SET application_status = :s",
                    ExpressionAttributeValues={':s': 'Evaluation Failed'}
                )
            except:
                pass
            raise e  # Re-raise so SQS retries the message

    return {"statusCode": 200, "body": "Batch processed."}