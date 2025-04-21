"""Flask application for AI-powered email outreach using CrewAI.

This module provides endpoints for generating and sending personalized outreach emails
using AI agents based on CrewAI framework.
"""

import os
import time
import yaml
from datetime import date

from flask import Flask, request, jsonify
from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import ScrapeWebsiteTool, SerperDevTool
from mailjet_rest import Client
import markdown2
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Initialize tools
search_tool = SerperDevTool(api_key=os.environ["SERPER_API_KEY"])
scrape_tool = ScrapeWebsiteTool()

# Load prompts from YAML file
def load_prompts():
    """Load prompts from YAML file.
    
    Returns:
        dict: Loaded prompts
    """
    try:
        with open('prompts.yaml', 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        return None

# Load prompts
PROMPTS = load_prompts()

class RetryAgent(Agent):
    """Agent with retry capability for handling flaky API calls."""

    def run_task_with_retries(self, task, max_retries=5):
        """Run task with retry mechanism in case of failure.

        Args:
            task: The task to run
            max_retries: Maximum number of retry attempts

        Returns:
            The result of the task or None if all attempts fail
        """
        attempt = 0
        while attempt < max_retries:
            try:
                result = self.run_task(task)
                if result is not None:
                    return result
            except Exception as exc:
                print(f"Attempt {attempt + 1} failed with error: {exc}")
                time.sleep(2)
            attempt += 1
        print(f"Max retries reached for task: {task.description}")
        return None

def setup_llm():
    """Set up and return the LLM configuration.

    Returns:
        LLM: Configured language model
    """
    return LLM(
        model="gemini/gemini-1.5-flash",
        api_key=os.environ["GEMINI_API_KEY"],
        custom_llm_provider="gemini"
    )

def create_agents(llm_instance):
    """Create and return the AI agents for the email generation process.

    Args:
        llm_instance: The language model to use for the agents

    Returns:
        tuple: The created agents
    """
    roles = PROMPTS['agent_roles']
    
    data_enrichment_agent = RetryAgent(
        role=roles['data_enrichment']['role'],
        goal=roles['data_enrichment']['goal'],
        backstory=roles['data_enrichment']['backstory'],
        verbose=True,
        allow_delegation=False,
        llm=llm_instance,
        tools=[search_tool, scrape_tool]
    )

    needs_analysis_agent = Agent(
        role=roles['needs_analysis']['role'],
        goal=roles['needs_analysis']['goal'],
        backstory=roles['needs_analysis']['backstory'],
        verbose=True,
        allow_delegation=False,
        llm=llm_instance,
        tools=[search_tool]
    )

    email_drafting_agent = Agent(
        role=roles['email_drafting']['role'],
        goal=roles['email_drafting']['goal'],
        backstory=roles['email_drafting']['backstory'],
        verbose=True,
        allow_delegation=False,
        llm=llm_instance
    )

    manager_agent = Agent(
        role=roles['manager']['role'],
        goal=roles['manager']['goal'],
        backstory=roles['manager']['backstory'],
        verbose=True,
        allow_delegation=True,
        llm=llm_instance
    )

    return data_enrichment_agent, needs_analysis_agent, email_drafting_agent, manager_agent


def create_tasks(data_agent, needs_agent, email_agent, manager_agent):
    """Create and return the tasks for the email generation process.

    Args:
        data_agent: The data enrichment agent
        needs_agent: The needs analysis agent
        email_agent: The email drafting agent
        manager_agent: The manager agent

    Returns:
        tuple: The created tasks
    """
    data_enrichment_task = Task(
        description=PROMPTS['enrichment_task_desc'],
        expected_output=PROMPTS['enrichment_output'],
        agent=data_agent
    )

    needs_analysis_task = Task(
        description=PROMPTS['needs_analysis_desc'],
        expected_output=PROMPTS['needs_analysis_output'],
        agent=needs_agent
    )

    email_drafting_task = Task(
        description=PROMPTS['email_drafting_desc'],
        expected_output=PROMPTS['email_drafting_output'],
        agent=email_agent
    )

    email_review_task = Task(
        description=PROMPTS['email_review_desc'],
        expected_output=PROMPTS['email_review_output'],
        agent=manager_agent
    )

    return data_enrichment_task, needs_analysis_task, email_drafting_task, email_review_task


def setup_crew(agents, tasks, llm_instance):
    """Set up and return the crew for email generation.

    Args:
        agents: The agents to include in the crew
        tasks: The tasks to assign to the crew
        llm_instance: The language model to use as manager

    Returns:
        Crew: The configured crew
    """
    return Crew(
        agents=agents[:3],  # First 3 agents
        tasks=tasks[:3],    # First 3 tasks
        manager_llm=llm_instance,
        process=Process.hierarchical,
        verbose=True
    )

@app.route("/generate_email", methods=["POST"])
def generate_email():
    """Generate a personalized outreach email based on input data.

    Returns:
        JSON response with generated email data or error message
    """
    data = request.json
    required_fields = [
        "company_name", "company_description", "campaign_description",
        "company_rep_name", "company_rep_role", "company_rep_email",
        "prospect_company_name", "prospect_rep_name", "prospect_rep_role",
        "prospect_rep_email"
    ]
    
    # Validate required fields
    missing_fields = [field for field in required_fields if field not in data or not data[field]]
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    inputs = {
        "company_name": data["company_name"],
        "company_description": data["company_description"],
        "campaign_description": data["campaign_description"],
        "company_rep_name": data["company_rep_name"],
        "company_rep_role": data["company_rep_role"],
        "company_rep_email": data["company_rep_email"],
        "prospect_company_name": data["prospect_company_name"],
        "prospect_rep_name": data["prospect_rep_name"],
        "prospect_rep_role": data["prospect_rep_role"],
        "prospect_rep_email": data["prospect_rep_email"],
        "today_date": date.today().strftime("%Y-%m-%d")
    }

    # Setup components
    my_llm = setup_llm()
    agents = create_agents(my_llm)
    tasks = create_tasks(*agents)
    email_outreach_crew = setup_crew(agents, tasks, my_llm)

    # Execute crew
    result = email_outreach_crew.kickoff(inputs=inputs)
    print(result)
    
    # Process the result
    return process_email_result(result, data)


def process_email_result(result, data):
    """Process the email generation result.
    
    Args:
        result: The result from the crew
        data: The original input data
        
    Returns:
        JSON response with the processed email data
    """
    email_body = str(result)

    # Extract subject and body
    lines = email_body.split("\n")
    subject = extract_subject(lines)
    
    if not subject:
        subject = "No subject found"

    # Filter out subject line from body
    filtered_lines = [line for line in lines if 'subject' not in line.lower()]
    email_body = markdown2.markdown("\n".join(filtered_lines))
    
    result_data = {
        "sender_email": data["company_rep_email"],
        "sender_name": data["company_rep_name"],
        "prospect_name": data["prospect_rep_name"],
        "prospect_email": data["prospect_rep_email"],
        "prospect_company_name": data["prospect_company_name"],
        "subject": subject,
        "body": email_body
    }

    return jsonify(result_data)

def extract_subject(lines):
    """Extract the subject line from the email content.
    
    Args:
        lines: The lines of the email content
        
    Returns:
        str: The extracted subject or None if not found
    """
    for line in lines:
        if 'subject' in line.lower():
            return line.strip().replace("Subject:", "").strip()
    return None

@app.route("/send_email", methods=["POST"])
def send_email():
    """Send an email using the Mailjet API.

    Returns:
        JSON response with success message or error details
    """
    data = request.json
    required_fields = [
        "from_email", "from_name", "to_email", "to_name",
        "subject", "body", "mailjet_api_key", "mailjet_api_secret"
    ]
    
    # Validate required fields
    missing_fields = [field for field in required_fields if field not in data or not data[field]]
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    # Initialize Mailjet client
    client = Client(
        auth=(data["mailjet_api_key"], data["mailjet_api_secret"]), 
        version='v3.1'
    )

    # Prepare email content
    email_content = {
        "from_email": data["from_email"],
        "from_name": data["from_name"],
        "to_email": data["to_email"],
        "to_name": data["to_name"],
        "subject": data["subject"],
        "body": data["body"]
    }

    try:
        response = send_email_via_mailjet(client, **email_content)
        if response.status_code == 200:
            return jsonify({"message": "Email sent successfully!"}), 200
        return jsonify({"error": "Failed to send email", "details": response.json()}), 500
    except Exception as exc:
        return jsonify({"error": f"Error sending email via Mailjet: {str(exc)}"}), 500

def send_email_via_mailjet(client, from_email, from_name, to_email, to_name, subject, body):
    """Send an email using the Mailjet client.

    Args:
        client: Initialized Mailjet client
        from_email: Sender's email address
        from_name: Sender's name
        to_email: Recipient's email address
        to_name: Recipient's name
        subject: Email subject
        body: HTML content of the email

    Returns:
        Response from Mailjet API
    """
    data = {
        'Messages': [
            {
                'From': {
                    'Email': from_email,
                    'Name': from_name
                },
                'To': [
                    {
                        'Email': to_email,
                        'Name': to_name
                    }
                ],
                'Subject': subject,
                'HTMLPart': body
            }
        ]
    }

    return client.send.create(data=data)

if __name__ == "__main__":
    app.run(debug=True)