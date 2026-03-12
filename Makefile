.PHONY: up down
# SUSPENDED LEGACY TARGETS: This Makefile operates the archived Neo4j stack.
# Do not use it for new deployment work; the supported backend is rest_server/
# with PostgreSQL.
# Detect Docker Compose command
DOCKER_COMPOSE = $(shell if command -v docker-compose > /dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)

# Check Neo4j health
check-neo4j-server:
	@while ! docker exec patra_neo4j_server cypher-shell -u neo4j -p PWD_HERE "RETURN 1" > /dev/null 2>&1; do \
		echo "neo4j-server starting..."; \
		sleep 5; \
	done

# Bring up services
up:
	$(DOCKER_COMPOSE) up -d

	$(MAKE) check-neo4j-server
	docker cp kg_config/constraints.cypher patra_neo4j_server:/constraints.cypher
	docker exec -it patra_neo4j_server cypher-shell -u neo4j -p PWD_HERE -f /constraints.cypher

# Bring down services
down:
	$(DOCKER_COMPOSE) down
