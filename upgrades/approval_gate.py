import logging
from typing import Optional

# Define the logger
logger = logging.getLogger(__name__)


class ApprovalGate:
    def __init__(self):
        self.proposals = {}

    def approve(self, proposal_id: str) -> bool:
        """Approve a proposal."""
        if proposal_id in self.proposals:
            self.proposals[proposal_id] = True
            logger.info(f"Approving proposal {proposal_id}")
            return True
        else:
            logger.error(f"Proposal {proposal_id} does not exist")
            return False

    def reject(self, proposal_id: str) -> bool:
        """Reject a proposal."""
        if proposal_id in self.proposals:
            self.proposals[proposal_id] = False
            logger.info(f"Rejecting proposal {proposal_id}")
            return True
        else:
            logger.error(f"Proposal {proposal_id} does not exist")
            return False

    def process_request(self, proposal_id: str, reject: bool = False) -> None:
        """Process a proposal request."""
        if reject:
            self.reject(proposal_id)
        else:
            self.approve(proposal_id)


def approve_or_reject(proposal_id: str, approval: bool) -> Optional[str]:
    """Approve or reject a proposal."""
    try:
        # Check if the proposal exists
        if not proposal_exists(proposal_id):
            logger.error(f"Proposal {proposal_id} does not exist")
            return None

        # Approve or reject the proposal
        if approval:
            approve_proposal(proposal_id)
            return f"Proposal {proposal_id} approved"
        else:
            reject_proposal(proposal_id)
            return f"Proposal {proposal_id} rejected"
    except Exception as e:
        logger.error(f"Error approving or rejecting proposal {proposal_id}: {e}")
        return None


def approve_proposal(proposal_id: str) -> None:
    """Approve a proposal."""
    # Implement the approval logic here
    # For demonstration purposes, assume the proposal is approved
    approval_gate = ApprovalGate()
    approval_gate.proposals[proposal_id] = True
    logger.info(f"Approving proposal {proposal_id}")


def reject_proposal(proposal_id: str) -> None:
    """Reject a proposal."""
    # Implement the rejection logic here
    # For demonstration purposes, assume the proposal is rejected
    approval_gate = ApprovalGate()
    approval_gate.proposals[proposal_id] = False
    logger.info(f"Rejecting proposal {proposal_id}")


def proposal_exists(proposal_id: str) -> bool:
    """Check if a proposal exists."""
    approval_gate = ApprovalGate()
    return proposal_id in approval_gate.proposals
