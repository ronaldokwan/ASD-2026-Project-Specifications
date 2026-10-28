"""Print a saved agentic-loop review (from release2_reviews.py) in a readable form.

    python student-5/validation/show_review.py docs/evidence/student-5/release-2/testing-review-ci/testing-review-review.json
"""

import json
import sys
import textwrap


def main(path):
    with open(path, encoding="utf-8") as handle:
        review = json.load(handle)
    result = dict(review.get("result") or {})
    log = result.pop("validation_log", {})
    print("mode:    ", review.get("mode"))
    print("model:   ", review.get("model"))
    print("status:  ", review.get("status"))
    print()
    print("result:")
    for key, value in result.items():
        print("  {}:".format(key))
        for line in textwrap.wrap(str(value), 130) or [""]:
            print("    " + line)
    print()
    print("validation_log:")
    print(textwrap.indent(json.dumps(log, indent=2), "  "))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
