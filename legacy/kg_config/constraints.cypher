CREATE CONSTRAINT model_id_unique IF NOT EXISTS
FOR (md:Model) REQUIRE md.model_id IS UNIQUE;

CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (user:User) REQUIRE user.user_id IS UNIQUE;

CREATE CONSTRAINT modelcard_id IF NOT EXISTS
FOR (mc:ModelCard) REQUIRE mc.external_id IS UNIQUE;

CREATE CONSTRAINT ai_model_id IF NOT EXISTS
FOR (ai:AIModel) REQUIRE ai.external_id IS UNIQUE;

CREATE CONSTRAINT model_id IF NOT EXISTS
FOR (m:Model) REQUIRE m.model_id IS UNIQUE;

CREATE CONSTRAINT datasheet_id IF NOT EXISTS
FOR (ds:Datasheet) REQUIRE ds.external_id IS UNIQUE;

CREATE CONSTRAINT deployment_id IF NOT EXISTS
FOR (depl:Deployment) REQUIRE depl.deployment_id IS UNIQUE;

CREATE VECTOR INDEX `modelEmbeddings` IF NOT EXISTS
FOR (m:ModelCard)
ON m.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 300, `vector.similarity_function`: 'cosine'}};

CREATE FULLTEXT INDEX mcFullIndex FOR (n:ModelCard) ON EACH
[n.name, n.short_description, n.full_description, n.keywords, n.author];
