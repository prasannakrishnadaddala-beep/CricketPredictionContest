#!/usr/bin/env python3
"""
deploy.py — One-command deploy to GitHub + Railway
Usage:
    python deploy.py --github-user YOUR_USERNAME --repo smart-predictor-league
"""

import argparse
import subprocess
import sys
import os


def run(cmd, check=True, capture=False):
    print(f"\n$ {cmd}")
    result = subprocess.run(
        cmd, shell=True, check=check,
        capture_output=capture, text=True
    )
    if capture:
        return result.stdout.strip()
    return result


def check_tool(name):
    result = subprocess.run(f"which {name}", shell=True, capture_output=True)
    if result.returncode != 0:
        print(f"❌  '{name}' not found. Please install it first.")
        sys.exit(1)
    print(f"✅  {name} found")


def main():
    parser = argparse.ArgumentParser(description="Deploy Smart Predictor League")
    parser.add_argument("--github-user", required=True, help="Your GitHub username")
    parser.add_argument("--repo", default="smart-predictor-league", help="GitHub repo name")
    parser.add_argument("--branch", default="main", help="Git branch")
    parser.add_argument("--skip-railway", action="store_true", help="Skip Railway deploy step")
    args = parser.parse_args()

    print("\n🚀  Smart Predictor League — Deploy Script")
    print("=" * 50)

    # 1. Check required tools
    print("\n[1/5] Checking required tools...")
    check_tool("git")
    check_tool("gh")    # GitHub CLI
    if not args.skip_railway:
        check_tool("railway")  # Railway CLI

    # 2. Init git if needed
    print("\n[2/5] Setting up Git...")
    if not os.path.exists(".git"):
        run("git init")
        run(f"git branch -M {args.branch}")
    else:
        print("  Git already initialised, skipping.")

    # 3. GitHub repo
    print(f"\n[3/5] Creating GitHub repo '{args.repo}'...")
    existing = subprocess.run(
        f"gh repo view {args.github_user}/{args.repo}",
        shell=True, capture_output=True
    )
    if existing.returncode == 0:
        print(f"  Repo already exists at github.com/{args.github_user}/{args.repo}")
        run(f"git remote set-url origin https://github.com/{args.github_user}/{args.repo}.git", check=False)
    else:
        run(f"gh repo create {args.repo} --public --source=. --remote=origin --push", check=False)

    # 4. Commit + push
    print("\n[4/5] Committing and pushing to GitHub...")
    run("git add -A")
    run('git commit -m "feat: initial Smart Predictor League deployment" --allow-empty')
    run(f"git push -u origin {args.branch} --force")

    print(f"\n✅  Code pushed to https://github.com/{args.github_user}/{args.repo}")

    # 5. Railway
    if not args.skip_railway:
        print("\n[5/5] Deploying to Railway...")
        run("railway login --browserless")
        run("railway init")
        run("railway up")

        print("\n📋  IMPORTANT: Set these environment variables in Railway dashboard:")
        env_vars = [
            ("SECRET_KEY",           "A long random string"),
            ("RAZORPAY_KEY_ID",      "From Razorpay dashboard"),
            ("RAZORPAY_KEY_SECRET",  "From Razorpay dashboard"),
            ("ADMIN_TOKEN",          "Your secret admin password"),
        ]
        for k, hint in env_vars:
            print(f"     {k:30s}  ← {hint}")
        print("\n     DATABASE_URL is set automatically when you add a PostgreSQL service in Railway.\n")
    else:
        print("\n[5/5] Skipped Railway deploy (--skip-railway flag).")
        print("\n📋  To deploy manually:")
        print("     1. Go to https://railway.app and create a new project")
        print("     2. Connect your GitHub repo")
        print("     3. Add a PostgreSQL service")
        print("     4. Set environment variables (see .env.example)")

    print("\n🎉  Done! Your app is being deployed.\n")


if __name__ == "__main__":
    main()
