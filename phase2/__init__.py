"""第二阶段：Agent 与本体层交互（OAG）"""

from .capability_provider import CapabilityProvider
from .agent_gateway import AgentGateway, GatewayResponse

__all__ = ["CapabilityProvider", "AgentGateway", "GatewayResponse"]
