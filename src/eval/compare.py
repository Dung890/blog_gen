"""Compare single-pass vs deep-research blogs on one topic, scored by the judge.

Run: python -m src.eval.compare
"""

import asyncio

from src.config.logging import configure_logging
from src.eval.judge import judge_blog
from src.graphs.graph_builder import GraphBuilder
from src.graphs.research_graph import DeepResearchGraphBuilder
from src.llms.groqllm import GroqLLM

TOPIC = "The health benefits of drinking green tea"


async def main() -> None:
    configure_logging()
    llm = GroqLLM().get_llm()

    single = await GraphBuilder(llm).setup_graph("topic").ainvoke({"topic": TOPIC})
    single_score = judge_blog(llm, TOPIC, single["blog"].get("content", ""))

    deep = await DeepResearchGraphBuilder(llm).build().ainvoke({"topic": TOPIC})
    deep_score = judge_blog(llm, TOPIC, deep["blog"].get("content", ""))

    print(f"\nTOPIC: {TOPIC}\n")
    print(f"{'dimension':12} {'single':>7} {'deep':>7}")
    for dim in ("grounding", "structure", "clarity", "seo", "overall"):
        print(f"{dim:12} {getattr(single_score, dim):>7} {getattr(deep_score, dim):>7}")
    if deep_score.overall > single_score.overall:
        winner = "deep"
    elif single_score.overall > deep_score.overall:
        winner = "single"
    else:
        winner = "tie"
    print(f"\nwinner (overall): {winner}")


if __name__ == "__main__":
    asyncio.run(main())
