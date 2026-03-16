import unittest
from unittest.mock import MagicMock, patch

from upgrades.approval_gate import ApprovalGate, approve_or_reject


class TestApprovalGate(unittest.TestCase):

    def test_approval_gate_init(self):
        """Test ApprovalGate initialization"""
        approval_gate = ApprovalGate()
        self.assertIsNotNone(approval_gate)

    def test_approve(self):
        """Test approve function"""
        approval_gate = ApprovalGate()
        approval_gate.approve = MagicMock(return_value=True)
        result = approval_gate.approve("test_request")
        self.assertTrue(result)

    def test_reject(self):
        """Test reject function"""
        approval_gate = ApprovalGate()
        approval_gate.reject = MagicMock(return_value=True)
        result = approval_gate.reject("test_request")
        self.assertTrue(result)

    @patch("upgrades.approval_gate.ApprovalGate.approve")
    @patch("upgrades.approval_gate.ApprovalGate.reject")
    def test_approval_gate_process_request(self, mock_reject, mock_approve):
        """Test ApprovalGate process_request method"""
        approval_gate = ApprovalGate()
        approval_gate.process_request("test_request")
        mock_approve.assert_called_once_with("test_request")
        mock_reject.assert_not_called()

    @patch("upgrades.approval_gate.ApprovalGate.approve")
    @patch("upgrades.approval_gate.ApprovalGate.reject")
    def test_approval_gate_process_request_reject(self, mock_reject, mock_approve):
        """Test ApprovalGate process_request method with reject"""
        approval_gate = ApprovalGate()
        approval_gate.reject = MagicMock(return_value=True)
        approval_gate.process_request("test_request", reject=True)
        mock_reject.assert_called_once_with("test_request")
        mock_approve.assert_not_called()

    def test_approve_or_reject(self):
        """Test approve_or_reject function"""
        proposal_id = "test_proposal"
        approval = True
        result = approve_or_reject(proposal_id, approval)
        self.assertEqual(result, f"Proposal {proposal_id} approved")


if __name__ == "__main__":
    unittest.main()
