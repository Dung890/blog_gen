"""The deep-research graph: planner -> parallel workers -> gap check -> synthesize -> write."""

from langgraph.graph import END, START, StateGraph

from src.nodes.research_node import ResearchNodes, assign_workers, route_after_gap
from src.states.research import DeepResearchState


class DeepResearchGraphBuilder:
    def __init__(self, llm):
        self.llm = llm
        self.nodes = ResearchNodes(llm)
        self.graph = StateGraph(DeepResearchState)

    def build(self):
        self.graph.add_node("planner", self.nodes.plan)
        self.graph.add_node("research_worker", self.nodes.worker)
        self.graph.add_node("gap_check", self.nodes.gap_check)
        self.graph.add_node("synthesize", self.nodes.synthesize)
        self.graph.add_node("write", self.nodes.write)
        self.graph.add_node("critic", self.nodes.critic)
        self.graph.add_node("revise", self.nodes.revise)

        self.graph.add_edge(START, "planner")
        # Dynamic parallel fan-out: one worker per assignment.
        self.graph.add_conditional_edges("planner", assign_workers, ["research_worker"])
        self.graph.add_edge("research_worker", "gap_check")
        # After gap check: loop back to workers for gaps, or proceed to synthesis.
        self.graph.add_conditional_edges(
            "gap_check",
            route_after_gap,
            {"proceed": "synthesize", "research_worker": "research_worker"},
        )
        self.graph.add_edge("synthesize", "write")
        self.graph.add_edge("write", "critic")
        # Two-part critic: revise on failure, or finish.
        self.graph.add_conditional_edges(
            "critic", self.nodes.route_after_critic, {"revise": "revise", "end": END}
        )
        self.graph.add_edge("revise", "critic")
        return self.graph.compile()
