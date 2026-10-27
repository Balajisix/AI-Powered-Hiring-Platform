import json
import boto3
from datetime import datetime

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('CandidatesTable')

stepfunctions = boto3.client('stepfunctions')

STATE_MACHINE_ARN = "arn:aws:states:us-east-1:594862215159:stateMachine:TechInterviewEmail" 


def lambda_handler(event, context):
    try:
        # Get candidate ID
        candidate_id = event['pathParameters']['id']

        # Logged-in user
        claims = event['requestContext']['authorizer']['jwt']['claims']
        evaluator_email = claims.get('email', 'Unknown Evaluator')

        # Request body
        body = json.loads(event.get('body', '{}'))
        new_status = body.get('status')
        tech_notes = body.get('tech_notes')
        tech_email = body.get('tech_email')

        print("DEBUG STATUS:", new_status)
        print("DEBUG TECH EMAIL:", tech_email)
        print("FULL BODY:", body)

        if not new_status:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "New status is required."})
            }

        # Build update query
        update_expr = "SET application_status = :s"
        expr_values = {':s': new_status}

        if tech_notes:
            update_expr += ", tech_evaluation_notes = :tn, tech_evaluator = :te, tech_eval_date = :td"
            expr_values[':tn'] = tech_notes
            expr_values[':te'] = evaluator_email
            expr_values[':td'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Update DB
        table.update_item(
            Key={'candidate_id': candidate_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values
        )

        print("DB Updated")

        # Fetch candidate details
        candidate = table.get_item(
            Key={'candidate_id': candidate_id}
        ).get('Item', {})

        candidate_name = candidate.get("candidate_name", "Candidate")
        candidate_email = candidate.get("candidate_email")

        print("Candidate:", candidate_name, candidate_email)

        if new_status and new_status.strip().lower() == "pending tech review" and tech_email:
            print("Triggering Step Function")

            stepfunctions.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({
                    "type": "TECH_ASSIGN",
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    "tech_email": tech_email
                })
            )
        elif new_status and new_status.strip().lower() == "manager review":
            print("Triggering Manager Notification")

            stepfunctions.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({
                    "type": "MANAGER_NOTIFY",
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    "manager_email": "balajivs0305@gmail.com"
                })
            )
        elif new_status and new_status.strip().lower() == "rejected":
            print("Triggering Rejection Email")

            stepfunctions.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({
                    "type": "HR_REJECT",
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email
                })
            )

        elif new_status and new_status.strip().lower() == "offer extended":
            print("Triggering Offer Email")

            stepfunctions.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({
                    "type": "MANAGER_OFFER",
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email
                })
            )


        elif new_status and new_status.strip().lower() == "rejected":
            print("Triggering Manager Rejection Email")

            stepfunctions.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                input=json.dumps({
                    "type": "MANAGER_REJECT",
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email
                })
            )

        else:
            print("Condition not matched for Step Function")

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "PATCH,OPTIONS"
            },
            "body": json.dumps({
                "message": "Status updated successfully"
            })
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Failed to update candidate"})
        }
