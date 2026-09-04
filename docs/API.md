# SerialCuts HTTP API

Сгенерировано из FastAPI-приложения командой `scripts/dump_openapi.py`.
Полная схема — в [`openapi.json`](openapi.json). Не редактируйте этот файл вручную.

## cache

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/cache` | Read Cache |
| `DELETE` | `/api/cache` | Delete Cache |

## candidates

| Метод | Путь | Описание |
| --- | --- | --- |
| `POST` | `/api/candidates/batch-render-job` | Batch Render Job |
| `PATCH` | `/api/candidates/{candidate_id}` | Update Candidate Edits |
| `POST` | `/api/candidates/{candidate_id}/auto-crop` | Auto Crop Candidate |
| `GET` | `/api/candidates/{candidate_id}/history` | Candidate History |
| `POST` | `/api/candidates/{candidate_id}/history/{snapshot_id}/restore` | Restore Candidate History |
| `GET` | `/api/candidates/{candidate_id}/keyframes` | Candidate Keyframes |
| `GET` | `/api/candidates/{candidate_id}/keyframes/{index}` | Candidate Keyframe Image |
| `POST` | `/api/candidates/{candidate_id}/preview` | Render Candidate Preview Endpoint |
| `GET` | `/api/candidates/{candidate_id}/preview-file` | Candidate Preview File |
| `GET` | `/api/candidates/{candidate_id}/quality` | Candidate Quality |
| `POST` | `/api/candidates/{candidate_id}/render` | Render Candidate Endpoint |
| `POST` | `/api/candidates/{candidate_id}/render-job` | Enqueue Candidate Render Endpoint |
| `POST` | `/api/candidates/{candidate_id}/review` | Review Candidate Endpoint |
| `GET` | `/api/candidates/{candidate_id}/subtitles` | Read Candidate Subtitles |
| `PUT` | `/api/candidates/{candidate_id}/subtitles` | Update Candidate Subtitles |
| `DELETE` | `/api/candidates/{candidate_id}/subtitles` | Reset Candidate Subtitles Endpoint |
| `POST` | `/api/candidates/{candidate_id}/subtitles/auto-split` | Auto Split Subtitles |
| `GET` | `/api/candidates/{candidate_id}/subtitles/quality` | Read Subtitle Quality |

## characters

| Метод | Путь | Описание |
| --- | --- | --- |
| `DELETE` | `/api/characters/{character_id}` | Delete Character |
| `POST` | `/api/characters/{character_id}/merge` | Merge Character Endpoint |
| `PUT` | `/api/characters/{character_id}/narration-voice` | Set Character Narration Voice |
| `POST` | `/api/characters/{character_id}/photos` | Add Character Reference Photo |
| `GET` | `/api/characters/{character_id}/photos/{photo_index}` | Character Photo |
| `DELETE` | `/api/characters/{character_id}/photos/{photo_index}` | Delete Character Photo |

## episodes

| Метод | Путь | Описание |
| --- | --- | --- |
| `DELETE` | `/api/episodes/{episode_id}` | Delete Episode Endpoint |
| `POST` | `/api/episodes/{episode_id}/auto-export` | Auto Export Episode |
| `GET` | `/api/episodes/{episode_id}/candidates` | List Episode Candidates |
| `POST` | `/api/episodes/{episode_id}/candidates/batch-review` | Batch Review |
| `POST` | `/api/episodes/{episode_id}/enqueue` | Enqueue Episode |
| `POST` | `/api/episodes/{episode_id}/identify-characters` | Identify Episode Characters |
| `GET` | `/api/episodes/{episode_id}/outline` | Read Episode Outline |
| `POST` | `/api/episodes/{episode_id}/probe` | Probe Episode |
| `GET` | `/api/episodes/{episode_id}/proxy` | Episode Proxy |
| `GET` | `/api/episodes/{episode_id}/quality` | Episode Quality |
| `GET` | `/api/episodes/{episode_id}/speaker-identities` | List Speaker Identities |
| `PUT` | `/api/episodes/{episode_id}/speaker-identities` | Update Speaker Identity |
| `GET` | `/api/episodes/{episode_id}/speaker-labels` | List Speaker Labels |
| `POST` | `/api/episodes/{episode_id}/stage2` | Run Stage2 Episode |
| `POST` | `/api/episodes/{episode_id}/stage3` | Run Stage3 Episode |
| `GET` | `/api/episodes/{episode_id}/story-context` | Read Story Context |
| `PUT` | `/api/episodes/{episode_id}/story-context` | Update Story Context |

## exports

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/exports` | List Exports |
| `GET` | `/api/exports/{export_id}/cover` | Export Cover |
| `GET` | `/api/exports/{export_id}/file` | Export File |
| `POST` | `/api/exports/{export_id}/open-folder` | Open Export Folder |

## health

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/health` | Health |

## jobs

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/jobs` | Jobs |
| `POST` | `/api/jobs/recover` | Recover Jobs |
| `DELETE` | `/api/jobs/{job_id}` | Delete Job Endpoint |
| `POST` | `/api/jobs/{job_id}/cancel` | Cancel Job |
| `POST` | `/api/jobs/{job_id}/retry` | Retry Job Endpoint |
| `POST` | `/api/jobs/{job_id}/retry-stage` | Retry Job From Stage Endpoint |
| `GET` | `/api/jobs/{job_id}/stages` | Job Stages |

## logs

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/logs` | Logs |

## model-catalog

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/model-catalog` | Get Model Catalog |
| `POST` | `/api/model-catalog/{key}/install` | Install Catalog Model |

## model-diagnostics

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/model-diagnostics` | Model Diagnostics |

## project-diagnostics

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/project-diagnostics` | Project Diagnostics |

## publishing-plans

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/publishing-plans` | Publishing Plans |
| `POST` | `/api/publishing-plans` | Create Publication |
| `PATCH` | `/api/publishing-plans/{plan_id}` | Patch Publication |
| `POST` | `/api/publishing-plans/{plan_id}/package` | Package Publication |

## queue

| Метод | Путь | Описание |
| --- | --- | --- |
| `POST` | `/api/queue/pause` | Pause Queue |
| `POST` | `/api/queue/resume` | Resume Queue |
| `POST` | `/api/queue/run-next` | Run Queue Next |

## seasons

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/seasons` | List Seasons |
| `POST` | `/api/seasons/import` | Import Season Endpoint |
| `DELETE` | `/api/seasons/{season_id}` | Delete Season Endpoint |
| `GET` | `/api/seasons/{season_id}/characters` | List Characters |
| `POST` | `/api/seasons/{season_id}/characters` | Create Character |
| `POST` | `/api/seasons/{season_id}/enqueue` | Enqueue Season |
| `GET` | `/api/seasons/{season_id}/search` | Search Season Endpoint |

## security-token

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/security-token` | Security Token |

## settings

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/settings` | Read Settings |
| `PUT` | `/api/settings` | Update Settings |

## story-arc-exports

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/story-arc-exports/{export_id}/cover` | Story Arc Export Cover |
| `GET` | `/api/story-arc-exports/{export_id}/file` | Story Arc Export File |

## story-arcs

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/story-arcs` | Story Arcs |
| `POST` | `/api/story-arcs` | Create Story Arc |
| `GET` | `/api/story-arcs/{story_arc_id}` | Read Story Arc |
| `PATCH` | `/api/story-arcs/{story_arc_id}` | Patch Story Arc |
| `DELETE` | `/api/story-arcs/{story_arc_id}` | Remove Story Arc |
| `GET` | `/api/story-arcs/{story_arc_id}/narration` | Read Story Arc Narration |
| `POST` | `/api/story-arcs/{story_arc_id}/narration-audio` | Create Story Arc Narration Audio |
| `GET` | `/api/story-arcs/{story_arc_id}/narration-audio-file` | Story Arc Narration Audio File |
| `POST` | `/api/story-arcs/{story_arc_id}/rebuild` | Rebuild Story Arc |
| `POST` | `/api/story-arcs/{story_arc_id}/render` | Render Story Arc Endpoint |
| `POST` | `/api/story-arcs/{story_arc_id}/render-job` | Enqueue Story Arc Render Endpoint |
| `POST` | `/api/story-arcs/{story_arc_id}/segments` | Add Story Arc Segment |
| `PATCH` | `/api/story-arcs/{story_arc_id}/segments/{segment_id}` | Patch Story Arc Segment |
| `DELETE` | `/api/story-arcs/{story_arc_id}/segments/{segment_id}` | Delete Story Arc Segment |

## system-check

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/system-check` | System Check |

## tts

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/tts/voices` | List Tts Voices |

## version

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/version` | Version |

## video-scripts

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/video-scripts` | Video Scripts |
| `POST` | `/api/video-scripts` | Create Script |
| `PATCH` | `/api/video-scripts/{script_id}` | Patch Script |

