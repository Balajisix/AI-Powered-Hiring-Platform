import json
import boto3
import os
from datetime import datetime

cognito = boto3.client('cognito-idp')
USER_POOL_ID = os.environ['USER_POOL_ID']

def lambda_handler(event, context):
    try:
        # Fetch all users from the Cognito Pool
        response = cognito.list_users(UserPoolId=USER_POOL_ID)
        users_data = []
        
        for user in response.get('Users', []):
            # Extract email from the Attributes array
            email = next((attr['Value'] for attr in user.get('Attributes', []) if attr['Name'] == 'email'), 'No Email')
            
            # Fetch the Role Group for this specific user
            groups_response = cognito.admin_list_groups_for_user(
                Username=user['Username'],
                UserPoolId=USER_POOL_ID
            )
            groups = [g['GroupName'] for g in groups_response.get('Groups', [])]
            primary_role = groups[0] if groups else 'UNASSIGNED'

            # Format the creation date
            created_date = user.get('UserCreateDate')
            if isinstance(created_date, datetime):
                created_date = created_date.strftime("%b %d, %Y")
            else:
                created_date = "Unknown"

            users_data.append({
                'id': user['Username'],
                'email': email,
                'status': user['UserStatus'],
                'createdDate': created_date,
                'role': primary_role
            })

        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET"
            },
            "body": json.dumps(users_data)
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": "Failed to fetch user directory."})
        }