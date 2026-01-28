#!/bin/bash

# Docker Compose Management Script

case "$1" in
  up)
    echo "🚀 Starting services..."
    docker compose up -d
    ;;
    
  down)
    echo "🛑 Stopping all services..."
    docker compose down
    ;;
    
  rebuild)
    echo "🧹 Stopping services..."
    docker compose down
    
    echo "🗑️  Removing images..."
    docker compose rm -f
    docker rmi $(docker compose config --images) 2>/dev/null || echo "No images to remove"
    
    echo "🔨 Building fresh images (no cache)..."
    docker compose build --no-cache
    
    echo "🚀 Starting services..."
    docker compose up -d
    
    echo "✅ Rebuild complete!"
    ;;
    
  logs)
    docker compose logs -f
    ;;
    
  *)
    echo "Usage: $0 {up|down|rebuild|logs}"
    echo ""
    echo "Commands:"
    echo "  up       - Start services"
    echo "  down     - Stop all services"
    echo "  rebuild  - Clean rebuild (stop, remove, build fresh, start)"
    echo "  logs     - Follow logs"
    exit 1
    ;;
esac
