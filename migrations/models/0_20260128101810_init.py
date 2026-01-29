from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "comfyui_workflows" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(100) NOT NULL UNIQUE,
    "description" TEXT,
    "workflow_json" JSON NOT NULL,
    "category" VARCHAR(50) NOT NULL DEFAULT 'general',
    "is_default" INT NOT NULL DEFAULT 0,
    "metadata" JSON NOT NULL
) /* ComfyUI 工作流配置模型。 */;
CREATE INDEX IF NOT EXISTS "idx_comfyui_wor_name_db14dc" ON "comfyui_workflows" ("name");
CREATE INDEX IF NOT EXISTS "idx_comfyui_wor_categor_d86ea7" ON "comfyui_workflows" ("category");
CREATE TABLE IF NOT EXISTS "users" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "username" VARCHAR(50) NOT NULL UNIQUE,
    "email" VARCHAR(255) NOT NULL UNIQUE,
    "hashed_password" VARCHAR(255) NOT NULL,
    "is_active" INT NOT NULL DEFAULT 1,
    "is_superuser" INT NOT NULL DEFAULT 0,
    "balance" VARCHAR(40) NOT NULL DEFAULT 0,
    "metadata" JSON NOT NULL
) /* 用户数据库模型。 */;
CREATE INDEX IF NOT EXISTS "idx_users_usernam_266d85" ON "users" ("username");
CREATE INDEX IF NOT EXISTS "idx_users_email_133a6f" ON "users" ("email");
CREATE TABLE IF NOT EXISTS "novels" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "title" VARCHAR(255) NOT NULL,
    "content" TEXT,
    "chapter_source" VARCHAR(9) NOT NULL DEFAULT 'extracted' /* EXTRACTED: extracted\nMANUAL: manual */,
    "author" VARCHAR(255),
    "status" VARCHAR(9) NOT NULL DEFAULT 'pending' /* PENDING: pending\nQUEUED: queued\nRUNNING: running\nCOMPLETED: completed\nFAILED: failed\nCANCELLED: cancelled */,
    "workflow_status" VARCHAR(20) NOT NULL DEFAULT 'draft' /* DRAFT: draft\nCHAPTERS_EXTRACTED: chapters_extracted\nCHARACTERS_EXTRACTED: characters_extracted\nSTORYBOARD_READY: storyboard_ready\nGENERATING: generating\nCOMPLETED: completed */,
    "total_chapters" INT NOT NULL DEFAULT 0,
    "processed_chapters" INT NOT NULL DEFAULT 0,
    "metadata" JSON NOT NULL,
    "user_id" CHAR(36) NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
) /* 小说数据库模型。 */;
CREATE INDEX IF NOT EXISTS "idx_novels_title_2d29a7" ON "novels" ("title");
CREATE INDEX IF NOT EXISTS "idx_novels_status_28057a" ON "novels" ("status");
CREATE INDEX IF NOT EXISTS "idx_novels_workflo_d69c0f" ON "novels" ("workflow_status");
CREATE TABLE IF NOT EXISTS "assets" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "asset_type" VARCHAR(6) NOT NULL /* PERSON: person\nSCENE: scene\nITEM: item */,
    "canonical_name" VARCHAR(100) NOT NULL,
    "aliases" JSON NOT NULL,
    "description" TEXT,
    "base_traits" TEXT,
    "main_image" VARCHAR(500),
    "angle_image_1" VARCHAR(500),
    "angle_image_2" VARCHAR(500),
    "image_source" VARCHAR(6) NOT NULL DEFAULT 'ai' /* AI: ai\nUPLOAD: upload */,
    "is_global" INT NOT NULL DEFAULT 1,
    "source_chapters" JSON NOT NULL,
    "last_updated_chapter" INT NOT NULL DEFAULT 0,
    "metadata" JSON NOT NULL,
    "novel_id" CHAR(36) NOT NULL REFERENCES "novels" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_assets_novel_i_ae40eb" UNIQUE ("novel_id", "asset_type", "canonical_name")
) /* 通用资产模型 - 人物\/场景\/物品。 */;
CREATE INDEX IF NOT EXISTS "idx_assets_asset_t_dafc50" ON "assets" ("asset_type");
CREATE INDEX IF NOT EXISTS "idx_assets_canonic_c7c8c9" ON "assets" ("canonical_name");
CREATE TABLE IF NOT EXISTS "chapters" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "number" INT NOT NULL,
    "title" VARCHAR(255) NOT NULL,
    "content" TEXT NOT NULL,
    "status" VARCHAR(9) NOT NULL DEFAULT 'pending' /* PENDING: pending\nQUEUED: queued\nRUNNING: running\nCOMPLETED: completed\nFAILED: failed\nCANCELLED: cancelled */,
    "workflow_status" VARCHAR(20) NOT NULL DEFAULT 'pending' /* PENDING: pending\nCHARACTERS_EXTRACTED: characters_extracted\nSTORYBOARD_READY: storyboard_ready\nGENERATING: generating\nCOMPLETED: completed */,
    "scene_count" INT NOT NULL DEFAULT 0,
    "metadata" JSON NOT NULL,
    "novel_id" CHAR(36) NOT NULL REFERENCES "novels" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_chapters_novel_i_dd748a" UNIQUE ("novel_id", "number")
) /* 章节数据库模型。 */;
CREATE INDEX IF NOT EXISTS "idx_chapters_number_64d2d5" ON "chapters" ("number");
CREATE INDEX IF NOT EXISTS "idx_chapters_status_00bcbb" ON "chapters" ("status");
CREATE INDEX IF NOT EXISTS "idx_chapters_workflo_0b815c" ON "chapters" ("workflow_status");
CREATE TABLE IF NOT EXISTS "chapter_assets" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "state_description" TEXT,
    "state_traits" TEXT,
    "appearances" JSON NOT NULL,
    "metadata" JSON NOT NULL,
    "asset_id" CHAR(36) NOT NULL REFERENCES "assets" ("id") ON DELETE CASCADE,
    "chapter_id" CHAR(36) NOT NULL REFERENCES "chapters" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_chapter_ass_chapter_5ad7fa" UNIQUE ("chapter_id", "asset_id")
) /* 章节与资产的关联，记录章节级别的状态变化。 */;
CREATE TABLE IF NOT EXISTS "extraction_tasks" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "task_type" VARCHAR(6) NOT NULL /* PERSON: person\nSCENE: scene\nITEM: item */,
    "status" VARCHAR(9) NOT NULL DEFAULT 'pending' /* PENDING: pending\nQUEUED: queued\nRUNNING: running\nCOMPLETED: completed\nFAILED: failed\nCANCELLED: cancelled */,
    "progress" INT NOT NULL DEFAULT 0,
    "message" VARCHAR(255),
    "retry_count" INT NOT NULL DEFAULT 0,
    "max_retries" INT NOT NULL DEFAULT 3,
    "timeout_seconds" INT NOT NULL DEFAULT 120,
    "result" JSON,
    "error" TEXT,
    "started_at" TIMESTAMP,
    "completed_at" TIMESTAMP,
    "chapter_id" CHAR(36) NOT NULL REFERENCES "chapters" ("id") ON DELETE CASCADE
) /* 资产提取任务模型 - 跟踪后台提取任务进度。 */;
CREATE INDEX IF NOT EXISTS "idx_extraction__task_ty_7f7745" ON "extraction_tasks" ("task_type");
CREATE INDEX IF NOT EXISTS "idx_extraction__status_b73e47" ON "extraction_tasks" ("status");
CREATE INDEX IF NOT EXISTS "idx_extraction__chapter_c82664" ON "extraction_tasks" ("chapter_id", "task_type", "status");
CREATE TABLE IF NOT EXISTS "scenes" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "sequence" INT NOT NULL,
    "description" TEXT NOT NULL,
    "dialogue" TEXT,
    "prompt" TEXT,
    "negative_prompt" TEXT,
    "image_url" VARCHAR(500),
    "audio_url" VARCHAR(500),
    "duration" REAL NOT NULL DEFAULT 0,
    "status" VARCHAR(9) NOT NULL DEFAULT 'pending' /* PENDING: pending\nQUEUED: queued\nRUNNING: running\nCOMPLETED: completed\nFAILED: failed\nCANCELLED: cancelled */,
    "metadata" JSON NOT NULL,
    "chapter_id" CHAR(36) NOT NULL REFERENCES "chapters" ("id") ON DELETE CASCADE,
    "speaker_id" CHAR(36) REFERENCES "assets" ("id") ON DELETE SET NULL,
    CONSTRAINT "uid_scenes_chapter_dcf1e4" UNIQUE ("chapter_id", "sequence")
) /* 场景数据库模型，表示单个分镜\/镜头。 */;
CREATE INDEX IF NOT EXISTS "idx_scenes_sequenc_aaf6fb" ON "scenes" ("sequence");
CREATE INDEX IF NOT EXISTS "idx_scenes_status_c3626b" ON "scenes" ("status");
CREATE TABLE IF NOT EXISTS "usage_records" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "resource_type" VARCHAR(50) NOT NULL,
    "quantity" REAL NOT NULL,
    "unit_cost" VARCHAR(40) NOT NULL,
    "total_cost" VARCHAR(40) NOT NULL,
    "description" VARCHAR(255),
    "metadata" JSON NOT NULL,
    "user_id" CHAR(36) NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
) /* 使用记录模型，用于计费。 */;
CREATE INDEX IF NOT EXISTS "idx_usage_recor_resourc_048a30" ON "usage_records" ("resource_type");
CREATE TABLE IF NOT EXISTS "videos" (
    "id" CHAR(36) NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "title" VARCHAR(255) NOT NULL,
    "url" VARCHAR(500),
    "duration" REAL NOT NULL DEFAULT 0,
    "resolution" VARCHAR(20) NOT NULL DEFAULT '1920x1080',
    "fps" INT NOT NULL DEFAULT 24,
    "status" VARCHAR(9) NOT NULL DEFAULT 'pending' /* PENDING: pending\nQUEUED: queued\nRUNNING: running\nCOMPLETED: completed\nFAILED: failed\nCANCELLED: cancelled */,
    "metadata" JSON NOT NULL,
    "chapter_id" CHAR(36) REFERENCES "chapters" ("id") ON DELETE SET NULL,
    "novel_id" CHAR(36) NOT NULL REFERENCES "novels" ("id") ON DELETE CASCADE
) /* 视频数据库模型。 */;
CREATE INDEX IF NOT EXISTS "idx_videos_status_068cc9" ON "videos" ("status");
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
)
