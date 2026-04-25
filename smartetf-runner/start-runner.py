"""
Local Runner Startup Script
Run this on your local machine to start the runner service
"""
import os
import sys
import subprocess
from pathlib import Path

def check_requirements():
    """Check if all requirements are met"""
    print("🔍 Checking requirements...")
    
    # Check if in runner directory
    if not Path("runner.py").exists():
        print("❌ Error: Must run from smartetf-runner directory")
        print("   cd /path/to/smartetf-runner")
        sys.exit(1)
    
    # Check if .env exists
    if not Path(".env").exists():
        print("⚠️  Warning: .env file not found")
        print("   Copy .env.example to .env and configure it")
        response = input("   Continue anyway? (y/n): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    # Check if dependencies installed
    try:
        import flask
        import sqlalchemy
        import selenium
        print("✅ Python dependencies installed")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("   Install requirements: pip install -r requirements.txt")
        sys.exit(1)
    
    # Check Chrome/Chromedriver for local
    try:
        result = subprocess.run(['google-chrome', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Chrome installed: {result.stdout.strip()}")
    except FileNotFoundError:
        print("⚠️  Chrome not found - some features may not work")
    
    print("")

def main():
    print("=" * 60)
    print("  SmartETF Local Runner Startup")
    print("=" * 60)
    print("")
    
    check_requirements()
    
    print("📋 Configuration:")
    print(f"   Working directory: {os.getcwd()}")
    print(f"   DB_URL: {os.getenv('DB_URL', 'Not set')[:50]}...")
    print(f"   RUNNER_TOKEN: {'Set' if os.getenv('RUNNER_TOKEN') else 'Not set'}")
    print(f"   RUN_MODE: {os.getenv('RUN_MODE', 'Not set')}")
    print("")
    
    print("🚀 Starting runner...")
    print("   Press Ctrl+C to stop")
    print("   Logs will appear below:")
    print("-" * 60)
    
    try:
        subprocess.run([sys.executable, 'runner.py'])
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("  Runner stopped")
        print("=" * 60)
        sys.exit(0)

if __name__ == '__main__':
    main()
