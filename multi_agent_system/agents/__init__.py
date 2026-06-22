from agents.customer_support import CustomerSupportAgent
from agents.recommendation import RecommendationAgent
from agents.fulfillment import FulfillmentAgent
from agents.inventory_planning import InventoryPlanningAgent
from models import AgentType

AGENT_REGISTRY = {
    AgentType.customer_support:   CustomerSupportAgent(),
    AgentType.recommendation:     RecommendationAgent(),
    AgentType.fulfillment:        FulfillmentAgent(),
    AgentType.inventory_planning: InventoryPlanningAgent(),
}


def get_agent(agent_type: AgentType):
    return AGENT_REGISTRY[agent_type]
