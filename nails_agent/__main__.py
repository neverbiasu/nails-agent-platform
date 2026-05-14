"""
CLI entry:
  python -m nails_agent run      — full pipeline
  python -m nails_agent trend    — step 1 only
  python -m nails_agent api      — start FastAPI server
  python -m nails_agent bot      — start Telegram bot
"""

import argparse
import logging
import sys

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)


def main():
    parser = argparse.ArgumentParser(prog="nails_agent")
    parser.add_argument("command", choices=["run", "trend", "api", "bot"])
    parser.add_argument("--data-dir", default="demo/data")
    parser.add_argument("--output-dir", default="demo/output")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    if args.command in ("run", "trend"):
        from nails_agent.agents.orchestrator import PipelineOrchestrator

        orch = PipelineOrchestrator(data_dir=args.data_dir, output_dir=args.output_dir)
        if args.command == "run":
            state = orch.run(progress_cb=print)
        else:
            state = orch.run_step1_only(progress_cb=print)
        print(f"\nPipeline ID: {state.pipeline_id}  Status: {state.status}")
        if state.errors:
            print("Errors:", state.errors)
        sys.exit(0 if state.status == "done" else 1)

    elif args.command == "api":
        import uvicorn

        uvicorn.run(
            "nails_agent.api.main:app",
            host=args.host,
            port=args.port,
            reload=False,
        )

    elif args.command == "bot":
        from nails_agent.bot.telegram import run_polling

        run_polling()


if __name__ == "__main__":
    main()
