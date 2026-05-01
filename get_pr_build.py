import subprocess
import json
import argparse
import re


def run_command(command, capture_output=True):
    if capture_output:
        result = subprocess.run(command, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            print(f"Error running command: {command}")
            print(result.stderr)
            return None
        return result.stdout.strip()
    else:
        return subprocess.call(command, shell=True)


def main():
    parser = argparse.ArgumentParser(description="Get latest PR build logs")
    parser.add_argument("--wait", action="store_true", help="Wait for the run to complete if it is pending")
    args = parser.parse_args()

    # 1. Get current branch
    branch = run_command("git rev-parse --abbrev-ref HEAD")
    if not branch:
        return

    # 2. Check for PR to main
    pr_json = run_command(f"gh pr list --head {branch} --base main --json number")
    if pr_json is None:
        return

    prs = json.loads(pr_json)
    if not prs:
        # If no PR to main, maybe just check runs for this branch
        pass
    else:
        pass  # PR found but number not currently used

    # 3. Get the latest run for this branch
    runs_json = run_command(f"gh run list --branch {branch} --limit 1 --json databaseId,status,conclusion,createdAt")
    if not runs_json:
        return

    runs = json.loads(runs_json)
    if not runs:
        print(f"No runs found for branch {branch}.")
        return

    latest_run = runs[0]
    run_id = latest_run["databaseId"]
    status = latest_run["status"]

    if status != "completed":
        if args.wait:
            print(f"Latest run is {status}. Waiting for it to complete...")
            run_command(f"gh run watch {run_id}", capture_output=False)
            # Re-fetch the run status for the specific run_id
            run_info_json = run_command(f"gh run view {run_id} --json status,conclusion")
            if not run_info_json:
                return
            run_info = json.loads(run_info_json)
            status = run_info["status"]
            conclusion = run_info["conclusion"]
        else:
            print(f"Latest run is {status} (not completed yet). Use --wait to wait for it.")
            return
    else:
        conclusion = latest_run["conclusion"]

    if conclusion == "success":
        print("SUCCESS")
        return

    if conclusion != "failure":
        print(f"Latest run completed with conclusion: {conclusion}")
        return

    # If it failed, we continue to extract logs
    # 4. Output the logs
    logs = run_command(f"gh run view {run_id} --log")
    if not logs:
        print("Could not retrieve logs.")
        return

    # 5. Filter for pytest output
    lines = logs.splitlines()
    pytest_lines = []
    found_pytest = False

    # Regex to match: JobName\tStepName\tTimestamp\tMessage
    # Sometimes it's spaces, sometimes tabs.
    log_pattern = re.compile(r"^.*?\t.*?\t\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\t(.*)$")
    # Alternative pattern if it's spaces
    alt_pattern = re.compile(r"^.*?\s+UNKNOWN STEP\s+\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s+(.*)$")

    for line in lines:
        if "test session starts" in line:
            found_pytest = True

        if found_pytest:
            match = log_pattern.match(line)
            if not match:
                match = alt_pattern.match(line)

            message = match.group(1) if match else line
            pytest_lines.append(message)

            # Stop if we see the final summary line
            # It usually looks like: ============= 2 failed, 345 passed, 1 warning in 241.18s (0:04:01) =============
            if "============= " in message and " in " in message and ("failed" in message or "passed" in message):
                break

    if pytest_lines:
        print("\n".join(pytest_lines))
    else:
        print("Could not find pytest output in the logs.")


if __name__ == "__main__":
    main()
