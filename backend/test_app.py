import unittest
import json
from unittest.mock import patch, MagicMock
from flask import Flask
import app

class TestEmailOutreachAppSimple(unittest.TestCase):

    def setUp(self):
        self.app = app.app.test_client()
        self.app.testing = True
        self.sample_email_data = {
            "company_name": "Acme Corp",
            "company_description": "Software company",
            "campaign_description": "Outreach campaign",
            "company_rep_name": "John Doe",
            "company_rep_role": "Sales Manager",
            "company_rep_email": "john.doe@acme.com",
            "prospect_company_name": "Beta Inc",
            "prospect_rep_name": "Jane Smith",
            "prospect_rep_role": "Marketing Lead",
            "prospect_rep_email": "jane.smith@beta.com"
        }
        self.sample_send_data = {
            "from_email": "dhanushsg144@gmail.com",
            "from_name": "From Name",
            "to_email": "dhanushsgowda277@gmail.com",
            "to_name": "To Name",
            "subject": "Test Email",
            "body": "<html><body>Test Body</body></html>",
            "mailjet_api_key": "test_key",
            "mailjet_api_secret": "test_secret"
        }
        self.sample_prompts = {'test': 'data'}

    @patch('app.load_prompts', return_value={'test': 'data'})
    def test_load_prompts_simple(self, mock_load_prompts):
        prompts = app.load_prompts()
        self.assertEqual(prompts, {'test': 'data'})
        mock_load_prompts.assert_called_once()

    def test_extract_subject_valid(self):
        lines = ["Subject: Test Subject", "Another line"]
        self.assertEqual(app.extract_subject(lines), "Test Subject")

    def test_extract_subject_missing(self):
        lines = ["No sub here"]
        self.assertIsNone(app.extract_subject(lines))

    def test_process_email_result_simple(self):
        result = "Subject: Test Email\n\nBody of the email."
        data = {"company_rep_email": "dhanushsg144@gmail.com", "company_rep_name": "Test Sender", "prospect_rep_name": "Test Recipient", "prospect_rep_email": "dhanushsgowda277@gmail.com", "prospect_company_name": "Test Co"}
        with self.app.application.test_request_context():
            response = app.process_email_result(result, data)
            self.assertEqual(response.status_code, 200)
            response_data = json.loads(response.get_data(as_text=True))
            self.assertEqual(response_data['subject'], "Test Email")
            self.assertIn("<p>Body of the email.</p>", response_data['body'])

    @patch('app.setup_llm')
    @patch('app.create_agents')
    @patch('app.create_tasks')
    @patch('app.setup_crew')
    def test_generate_email_success_status(self, mock_setup_crew, mock_create_tasks, mock_create_agents, mock_setup_llm):
        mock_llm_instance = MagicMock()
        mock_setup_llm.return_value = mock_llm_instance
        mock_agents = [MagicMock()] * 4
        mock_create_agents.return_value = tuple(mock_agents)
        mock_tasks = [MagicMock()] * 4
        mock_create_tasks.return_value = tuple(mock_tasks)
        mock_crew_instance = MagicMock()
        mock_crew_instance.kickoff.return_value = "Subject: Test Generated Email\n\nThis is the body."
        mock_setup_crew.return_value = mock_crew_instance

        response = self.app.post('/generate_email', json=self.sample_email_data)
        self.assertEqual(response.status_code, 200)

    def test_generate_email_missing_fields_status(self):
        response = self.app.post('/generate_email', json={})
        self.assertEqual(response.status_code, 400)

    @patch('app.send_email_via_mailjet')
    def test_send_email_success_status(self, mock_send_email):
        mock_send_email.return_value = MagicMock(status_code=200)
        response = self.app.post('/send_email', json=self.sample_send_data)
        self.assertEqual(response.status_code, 200)

    @patch('app.send_email_via_mailjet')
    def test_send_email_failure_status(self, mock_send_email):
        mock_send_email.return_value = MagicMock(status_code=500)
        response = self.app.post('/send_email', json=self.sample_send_data)
        self.assertEqual(response.status_code, 500)

    def test_send_email_missing_fields_status_send(self):
        response = self.app.post('/send_email', json={})
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()