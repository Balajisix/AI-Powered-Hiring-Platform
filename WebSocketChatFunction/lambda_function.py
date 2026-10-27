import boto3
import os
import copy
import re
import json

dynamodb = boto3.resource('dynamodb')
chat_table = dynamodb.Table(os.environ['TABLE_NAME'])
main_table = dynamodb.Table('CandidatesTable')
s3 = boto3.client('s3')
bedrock = boto3.client('bedrock-runtime')
stepfunctions = boto3.client('stepfunctions')


# HELPERS

def get_resume_context(candidate_id):
    try:
        candidate = main_table.get_item(Key={'candidate_id': candidate_id}).get('Item', {})
        resume_key = candidate.get('resume_s3_key', '')

        if not resume_key:
            return [], ''

        s3_response = s3.get_object(Bucket=os.environ['RESUME_BUCKET'], Key=resume_key)
        pdf_bytes = s3_response['Body'].read()

        if not pdf_bytes.startswith(b'%PDF-'):
            return [], ''

        resume_context = [{"document": {"name": "resume", "format": "pdf", "source": {"bytes": pdf_bytes}}}]
        return resume_context, candidate.get('job_id', '')

    except Exception as e:
        print(f"Resume load error: {repr(e)}")
        return [], ''


def get_jd(job_id):
    try:
        jobs_table = dynamodb.Table(os.environ['JD_TABLE_NAME'])
        job = jobs_table.get_item(Key={'id': job_id}).get('Item', {})
        return job.get('job_description', '')
    except:
        return ''


def inject_resume(messages, resume_context):
    if messages and messages[0]['role'] == 'user' and resume_context:
        messages[0]['content'] = resume_context + [
            block for block in messages[0]['content'] if 'document' not in block
        ]
    return messages


def format_transcript(history):
    lines = []
    for msg in history:
        role = "Interviewer" if msg['role'] == 'assistant' else "Candidate"
        text = " ".join([b.get('text', '') for b in msg['content'] if 'text' in b])
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def parse_json_safe(text):
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        return json.loads(match.group(0)) if match else {}
    except:
        return {}


# MAIN HANDLER

def lambda_handler(event, context):

    route_key = event.get('requestContext', {}).get('routeKey')

    if route_key in ['$connect', '$disconnect']:
        return {"statusCode": 200}

    connection_id = event['requestContext']['connectionId']
    domain = event['requestContext']['domainName']
    stage = event['requestContext']['stage']
    apigw = boto3.client('apigatewaymanagementapi', endpoint_url=f"https://{domain}/{stage}")

    try:
        body = json.loads(event.get('body', '{}'))
        action = body.get('action')

        if action == 'ping':
            return {"statusCode": 200}

        candidate_id = body.get('candidate_id')
        if not candidate_id:
            return {"statusCode": 400}

        session = chat_table.get_item(Key={'candidate_id': candidate_id}).get('Item', {})
        history = session.get('messages', [])
        turn_count = session.get('turn_count', 0)

        resume_context, job_id = get_resume_context(candidate_id)
        jd = get_jd(job_id)

        # ───────── START INTERVIEW ─────────
        if action == 'start_interview':

            turn_count = 0
            history = []

            sys_prompt = f"""
You are a highly experienced senior technical interviewer.

Context:
- Resume is attached
- Job Description: {jd}

TASK:
1. Start with a personalized greeting referencing a SPECIFIC detail from the resume.
2. Ask ONE high-quality technical question.

RULES:
- Question must be:
  - Relevant to JD OR resume
  - Not generic
  - Not theoretical only → prefer practical/real-world
- Avoid basic questions
- Max 2 sentences total
- Do NOT ask multiple questions
"""

            messages = [{
                "role": "user",
                "content": resume_context + [{"text": "Start interview"}]
            }]

            response = bedrock.converse(
                modelId="amazon.nova-pro-v1:0",
                messages=messages,
                system=[{"text": sys_prompt}],
                inferenceConfig={"temperature": 0.3}
            )

            ai_reply = response['output']['message']['content'][0]['text']

            history = [
                {"role": "user", "content": [{"text": "Start interview"}]},
                {"role": "assistant", "content": [{"text": ai_reply}]}
            ]

            chat_table.put_item(Item={
                'candidate_id': candidate_id,
                'messages': history,
                'turn_count': 1
            })

            apigw.post_to_connection(ConnectionId=connection_id,
                                     Data=json.dumps({"reply": ai_reply}).encode('utf-8'))

            return {"statusCode": 200}

        # ───────── INTERVIEW LOOP ─────────
        elif action == 'sendMessage':

            user_message = body.get('message', '')
            history.append({"role": "user", "content": [{"text": user_message}]})
            turn_count += 1

            clean_history = copy.deepcopy(history)
            for msg in clean_history:
                msg['content'] = [b for b in msg['content'] if 'document' not in b]

            clean_history = inject_resume(clean_history, resume_context)

            # ─── ASK QUESTIONS ───
            if turn_count <= 4:

                sys_prompt = f"""
You are a strict senior technical interviewer.

Context:
- Resume attached
- JD: {jd}

INTERVIEW RULES:
1. First word: ONLY "Understood." or "Noted."
2. Then ask ONE challenging question

QUESTION STRATEGY:
- Alternate:
  a) Resume deep dive (projects, architecture, decisions)
  b) JD skill validation (real-world problems)

STRICT:
- No hints
- No teaching
- No multiple questions
- Avoid generic theory
- Force candidate to THINK

This is question {turn_count + 1}/5
Max 2 sentences total
"""

                response = bedrock.converse(
                    modelId="amazon.nova-pro-v1:0",
                    messages=clean_history,
                    system=[{"text": sys_prompt}],
                    inferenceConfig={"temperature": 0.2}
                )

                ai_reply = response['output']['message']['content'][0]['text']

                history.append({"role": "assistant", "content": [{"text": ai_reply}]})

                chat_table.put_item(Item={
                    'candidate_id': candidate_id,
                    'messages': history,
                    'turn_count': turn_count
                })

                apigw.post_to_connection(ConnectionId=connection_id,
                                         Data=json.dumps({"reply": ai_reply}).encode('utf-8'))

            # ─── FINAL EVALUATION ───
            elif turn_count >= 5:

                goodbye_msg = "Thank you for your time! Interview completed."

                apigw.post_to_connection(ConnectionId=connection_id,
                                         Data=json.dumps({"reply": goodbye_msg, "status": "completed"}).encode('utf-8'))

                history.append({"role": "assistant", "content": [{"text": goodbye_msg}]})

                chat_table.put_item(Item={
                    'candidate_id': candidate_id,
                    'messages': history,
                    'turn_count': turn_count
                })

                try:
                    transcript_text = format_transcript(history)

                    eval_prompt = f"""
                    You are a strict and unbiased senior technical interviewer.

                    Context:
                    - Resume is already provided
                    - Job Description (JD): {jd}

                    FULL INTERVIEW TRANSCRIPT:
                    {transcript_text}

                    ---

                    EVALUATION INSTRUCTIONS:

                    Score the candidate using FULL RANGE (0–100).
                    ⚠️ DO NOT cluster scores around 50–60.

                    SCORING DISTRIBUTION (STRICT):

                    - Excellent → 75–100
                    - Good → 60–74
                    - Average → 40–59
                    - Poor → 0–39

                    ---

                    SCORING DIMENSIONS (calculate internally):

                    1. Technical Accuracy (0-25)
                    2. Relevance to JD (0-15)
                    3. Resume Consistency (0-10)
                    4. Problem Solving (0-15)
                    5. Depth of Knowledge (0-10)
                    6. Communication (0-10)
                    7. Authenticity (0-15)

                    ---

                    STRICT RULES:

                    - Penalize vague / incorrect answers heavily
                    - Penalize generic answers
                    - If candidate struggles → score MUST go below 40
                    - If candidate is strong → score MUST go above 70
                    - Avoid safe middle scoring

                    ---

                    DECISION RULES:

                    - Score >= 75 → Proceed to Technical Round
                    - Score 50–74 → Borderline – Needs Further Evaluation
                    - Score < 40 → Rejected

                    ---

                    OUTPUT STRICT JSON ONLY:

                    {{
                    "interview_score": <integer>,
                    "decision": "<Proceed to Technical Round | Borderline – Needs Further Evaluation | Rejected>",
                    "feedback": "<2-3 lines: strengths + weaknesses + hiring risk>"
                    }}
                    """

                    # 🔥 SINGLE EVALUATION (NO AVERAGING)
                    response = bedrock.converse(
                        modelId="amazon.nova-pro-v1:0",
                        messages=[{"role": "user", "content": [{"text": "Evaluate candidate"}]}],
                        system=[{"text": eval_prompt}],
                        inferenceConfig={"temperature": 0.2}
                    )

                    raw_output = response['output']['message']['content'][0]['text']
                    eval_result = parse_json_safe(raw_output)

                    print("🔍 RAW EVAL OUTPUT:", raw_output)
                    print("✅ PARSED EVAL:", eval_result)

                    score = int(eval_result.get('interview_score', 0))
                    final_decision = eval_result.get('decision', 'Borderline – Needs Further Evaluation')
                    feedback = eval_result.get('feedback', 'No feedback provided')

                    if final_decision == "Proceed to Technical Round":
                        application_status = "Interview Passed"
                    elif "Borderline" in final_decision:
                        application_status = "Need Review"
                    else:
                        application_status = "Interview Failed"

                    # 🛡️ SAFETY GUARD (avoid weird outputs)
                    if score < 0:
                        score = 0
                    elif score > 100:
                        score = 100

                    # 🚀 FINAL RESULT
                    final_result = {
                        "interview_score": score,
                        "decision": final_decision,
                        "feedback": feedback
                    }

                    print("🎯 FINAL RESULT:", final_result)

                    # 📥 Get candidate
                    candidate = main_table.get_item(
                        Key={'candidate_id': candidate_id}
                    ).get('Item', {})

                    # 🚀 TRIGGER STEP FUNCTION
                    stepfunctions.start_execution(
                        stateMachineArn=os.environ['STATE_MACHINE_ARN'],
                        input=json.dumps({
                            "candidate_name": candidate.get("candidate_name", "Candidate"),
                            "candidate_email": candidate.get("candidate_email"),
                            "hr_email": "vhaniprakaash018@gmail.com",
                            "score": score,
                            "decision": final_decision
                        })
                    )

                    # 💾 SAVE TO DB
                    main_table.update_item(
                        Key={'candidate_id': candidate_id},
                        UpdateExpression="""
                            SET interview_score=:s,
                                interview_feedback=:f,
                                interview_decision=:d,
                                application_status=:a
                        """,
                        ExpressionAttributeValues={
                            ':s': score,
                            ':f': feedback,
                            ':d': final_decision,
                            ':a': application_status
                        }
                    )

                except Exception as e:
                    print("❌ Eval error:", repr(e))

        return {"statusCode": 200}

    except Exception as e:
        print("Error:", repr(e))
        return {"statusCode": 500}