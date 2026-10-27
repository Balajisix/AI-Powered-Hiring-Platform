import json
import boto3

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('InterviewSessions') 

def lambda_handler(event, context):
    try:
        candidate_id = event['pathParameters']['id']
        response = table.get_item(Key={'candidate_id': candidate_id})
        
        if 'Item' not in response:
            return {
                "statusCode": 404,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"error": "Transcript not found"})
            }
            
        messages = response['Item'].get('messages', [])
        
        clean_messages = []
        for msg in messages:
            text_content = ""
            for block in msg.get('content', []):
                if 'text' in block:
                    text_content += block['text']
            
            clean_messages.append({
                "role": msg.get('role'),
                "text": text_content
            })

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET"
            },
            "body": json.dumps(clean_messages)
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Failed to fetch transcript"})
        }
