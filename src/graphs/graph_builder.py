"""Assembles the LangGraph pipelines for blog generation.

Two use cases:

- ``"topic"``   : title -> content
- ``"language"``: title -> content -> translation (into any language)

The translation step is a single dynamic node that reads the target language
from the state, so it supports any language - no per-language nodes or hardcoded
routing.
"""

from langgraph.graph import END, START, StateGraph

from src.llms.groqllm import GroqLLM
from src.nodes.blog_node import BlogNode
from src.states.blogstate import BlogState


class GraphBuilder:
    def __init__(self, llm, llm_strong=None):
        self.llm = llm
        self.llm_strong = llm_strong or llm
        self.graph = StateGraph(BlogState)
        self.blog_node_obj = BlogNode(self.llm, self.llm_strong)

    def build_topic_graph(self):
        """Blog from a topic, with a self-critique/revise loop."""
        self.graph.add_node("title_creation", self.blog_node_obj.title_creation)
        self.graph.add_node("content_generation", self.blog_node_obj.content_generation)
        self.graph.add_node("critique_draft", self.blog_node_obj.critique)
        self.graph.add_node("revise", self.blog_node_obj.revise)
        self.graph.add_node("do_research", self.blog_node_obj.research)

        self.graph.add_edge(START, "title_creation")
        self.graph.add_edge("title_creation", "do_research")
        self.graph.add_edge("do_research", "content_generation")
        self.graph.add_edge("content_generation", "critique_draft")

        # Conditional edge: after critique, the router returns "revise" or "end".
        # The mapping says which node each of those strings goes to.
        self.graph.add_conditional_edges(
            "critique_draft",
            self.blog_node_obj.route_after_critique,
            {"revise": "revise", "end": END},
        )
        # The loop: after revising, go back to critique to re-judge.
        self.graph.add_edge("revise", "critique_draft")
        return self.graph

    def build_language_graph(self):
        """Blog plus translation: title -> content -> translation.

        A single ``translation`` node handles every language by reading
        ``current_language`` from the state, replacing the old hindi/french
        conditional branches.
        """
        self.graph.add_node("title_creation", self.blog_node_obj.title_creation)
        self.graph.add_node("content_generation", self.blog_node_obj.content_generation)
        self.graph.add_node("translation", self.blog_node_obj.translation)

        self.graph.add_edge(START, "title_creation")
        self.graph.add_edge("title_creation", "content_generation")
        self.graph.add_edge("content_generation", "translation")
        self.graph.add_edge("translation", END)
        return self.graph

    def setup_graph(self, usecase: str):
        """Build and compile the graph for the given use case."""
        if usecase == "topic":
            self.build_topic_graph()
        elif usecase == "language":
            self.build_language_graph()
        else:
            raise ValueError(f"Unknown usecase: {usecase!r}")
        return self.graph.compile()


def _build_default_graph():
    """Build the default (language) graph with a live Groq LLM."""
    return GraphBuilder(GroqLLM().get_llm()).build_language_graph().compile()


def __getattr__(name):
    """Lazily expose ``graph`` for LangGraph Studio / langgraph.json.

    Using module-level ``__getattr__`` (PEP 562) means simply importing this
    module - e.g. to use the ``GraphBuilder`` class or in tests - does NOT
    construct an LLM or require an API key. The graph is built only when
    something accesses ``graph_builder.graph``, which is what Studio does.
    """
    if name == "graph":
        return _build_default_graph()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
