"""Generate a blog for each dataset topic and score it with the LLM judge.

Run: python -m src.eval.run_eval
"""

import asyncio
from statistics import mean

from src.config.logging import configure_logging
from src.eval.dataset import TOPICS
from src.eval.judge import Score, judge_blog
from src.graphs.graph_builder import GraphBuilder
from src.llms.groqllm import GroqLLM


async def evaluate_topic(graph, llm, topic: str) -> Score:
    state = await graph.ainvoke({"topic": topic})
    content = state["blog"].get("content", "")
    return judge_blog(llm, topic, content)


async def main() -> None:
    configure_logging()
    llm = GroqLLM().get_llm()
    graph = GraphBuilder(llm).setup_graph("topic")

    scores: list[Score] = []
    for topic in TOPICS:
        score = await evaluate_topic(graph, llm, topic)
        scores.append(score)
        print(f"\n=== {topic} ===")
        print(
            f"  grounding={score.grounding} structure={score.structure} "
            f"clarity={score.clarity} seo={score.seo} overall={score.overall}"
        )
        print(f"  {score.rationale}")

    print("\n=== AVERAGES ===")
    print(f"  overall avg: {mean(s.overall for s in scores):.1f}")


if __name__ == "__main__":
    asyncio.run(main())
