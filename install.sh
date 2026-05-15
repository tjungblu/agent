#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "🚀 Installing Developer Workflow Agent..."
echo

# Check dependencies
echo "📋 Checking dependencies..."
missing_deps=()

if ! command -v uv &> /dev/null; then
    missing_deps+=("uv (install: curl -LsSf https://astral.sh/uv/install.sh | sh)")
fi

if ! command -v gh &> /dev/null; then
    missing_deps+=("gh (install: https://cli.github.com/)")
fi

if ! command -v npx &> /dev/null; then
    missing_deps+=("npx/node (install: https://nodejs.org/)")
fi

if [ ${#missing_deps[@]} -ne 0 ]; then
    echo "❌ Missing dependencies:"
    for dep in "${missing_deps[@]}"; do
        echo "   - $dep"
    done
    exit 1
fi

echo "✓ All dependencies found"
echo

# Check for .env file
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "❌ .env file not found!"
    echo "   Copy .env.example to .env and configure it:"
    echo "   cp .env.example .env"
    echo "   vim .env"
    exit 1
fi

echo "✓ .env file found"
echo

# Install Python dependencies
echo "📦 Installing Python dependencies..."
cd "$SCRIPT_DIR"
uv sync
echo "✓ Dependencies installed"
echo

# Create systemd user directory
echo "📁 Setting up systemd user services..."
mkdir -p "$SYSTEMD_USER_DIR"

# Detect npx path
NPX_PATH=$(which npx)
if [ -z "$NPX_PATH" ]; then
    echo "❌ npx not found in PATH"
    exit 1
fi
echo "✓ Found npx at: $NPX_PATH"

# Detect uv path
UV_PATH=$(which uv)
if [ -z "$UV_PATH" ]; then
    echo "❌ uv not found in PATH"
    exit 1
fi
echo "✓ Found uv at: $UV_PATH"

# Copy systemd files and substitute paths
sed "s|UV_PATH|$UV_PATH|g" "$SCRIPT_DIR/systemd/agent-morning-brief.service" > "$SYSTEMD_USER_DIR/agent-morning-brief.service"
sed "s|UV_PATH|$UV_PATH|g" "$SCRIPT_DIR/systemd/agent-hourly-brief.service" > "$SYSTEMD_USER_DIR/agent-hourly-brief.service"
sed "s|UV_PATH|$UV_PATH|g" "$SCRIPT_DIR/systemd/agent-labeler.service" > "$SYSTEMD_USER_DIR/agent-labeler.service"
cp "$SCRIPT_DIR/systemd/agent-morning-brief.timer" "$SYSTEMD_USER_DIR/"
cp "$SCRIPT_DIR/systemd/agent-hourly-brief.timer" "$SYSTEMD_USER_DIR/"
cp "$SCRIPT_DIR/systemd/agent-labeler.timer" "$SYSTEMD_USER_DIR/"

echo "✓ Systemd files copied"
echo

# Reload systemd
echo "🔄 Reloading systemd..."
systemctl --user daemon-reload

# Stop old jira-mcp service if it exists
if systemctl --user is-active --quiet jira-mcp.service; then
    echo "🛑 Stopping old jira-mcp.service..."
    systemctl --user stop jira-mcp.service
    systemctl --user disable jira-mcp.service
fi

# Enable and start services
echo "🎯 Enabling timers..."
systemctl --user enable agent-morning-brief.timer
systemctl --user enable agent-hourly-brief.timer
systemctl --user enable agent-labeler.timer

echo "▶️  Starting timers..."
systemctl --user start agent-morning-brief.timer
systemctl --user start agent-hourly-brief.timer
systemctl --user start agent-labeler.timer

echo "✓ Timers started"
echo

# Show status
echo "📊 Timer Status:"
echo
echo "Morning Brief Timer:"
systemctl --user status agent-morning-brief.timer --no-pager -l
echo
echo "Hourly Brief Timer:"
systemctl --user status agent-hourly-brief.timer --no-pager -l
echo
echo "Bot PR Labeler Timer:"
systemctl --user status agent-labeler.timer --no-pager -l
echo

echo "✅ Installation complete!"
