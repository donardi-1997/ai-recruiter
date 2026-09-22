from __future__ import annotations

import sys

from tools.indeed_resume_agent.main import main


def entrypoint() -> None:
    if "--self-test" in sys.argv[1:]:
        from tools.indeed_resume_agent.self_test import run_self_test

        raise SystemExit(run_self_test())
    main()


if __name__ == "__main__":
    entrypoint()
