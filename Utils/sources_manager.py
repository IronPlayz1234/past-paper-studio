"""Multi-source paper fetching with fallbacks and compound-resource grouping."""

from __future__ import annotations
from Core.runtime_paths import cache_path
from Core.atomic_storage import atomic_write_json
from Core.cache_tools import synchronized

import os
import re
import json
import time
import hashlib
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

import requests

from Core.runtime_tuning import (
    configure_search_logging,
    file_buffer_size_bytes,
    get_search_logger,
    maybe_collect_garbage,
)
from Data.igcse_components_registry import get_subject_row, normalize_paper_number
from Data.alevel_profiles import get_alevel_paper
from Utils.gui_utils import (
    ComponentsDatabase,
    ConfigManager,
    SubjectDatabase,
    get_subject_folder,
    series_to_code,
)


class PaperNotFoundError(Exception):
    """Raised when no papers are found on any configured source."""

    pass


@dataclass(slots=True)
class PaperResource:
    """A single downloadable document attached to a paper group."""

    kind: str
    filename: str
    url: str
    source: str
    downloaded: bool = False
    direct_url: str = ""
    viewer_url: str = ""
    open_url: str = ""
    download_url: str = ""
    resource_family: str = ""
    resource_token: str = ""
    extension: str = ""

    def __post_init__(self) -> None:
        direct = str(self.direct_url or self.url or "").strip()
        viewer = str(self.viewer_url or "").strip()
        open_url = str(self.open_url or "").strip()
        download_url = str(self.download_url or "").strip()
        ext = str(self.extension or "").strip().lower().lstrip(".")

        self.direct_url = direct
        self.url = direct
        self.viewer_url = viewer
        self.extension = ext or os.path.splitext(str(self.filename or ""))[1].lower().lstrip(".")

        if not open_url:
            if self.extension == "pdf" and viewer:
                open_url = viewer
            else:
                open_url = direct
        if not download_url:
            download_url = direct

        self.open_url = open_url
        self.download_url = download_url


@dataclass(slots=True)
class PapacambridgeDocRef:
    """Parsed PapaCambridge listing row for one file."""

    filename: str
    subject_code: str
    year: str
    session: str
    component: str
    doc_token: str
    direct_url: str
    viewer_url: str = ""


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Normalized description of a paper search request."""

    subject_code: str
    level: str
    series_list: List[str]
    components: List[str]
    years: List[str]
    doc_types: List[str]

    def fingerprint(self) -> str:
        """Stable, short identifier used for logging and deduplication."""
        payload = {
            "subject": str(self.subject_code or "").strip(),
            "series": sorted(
                {str(s).strip().upper() for s in self.series_list or [] if str(s).strip()}
            ),
            "components": sorted(
                {str(c).strip() for c in self.components or [] if str(c).strip()}
            ),
            "years": sorted(
                {str(y).strip() for y in self.years or [] if str(y).strip()}
            ),
            "doc_types": sorted(
                {str(dt).strip().upper() for dt in self.doc_types or [] if str(dt).strip()}
            ),
            "level": str(self.level or "").strip(),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


class SourceProvider:
    """Interface for a single upstream paper source."""

    name: str

    def search(
        self,
        manager: "PaperSourceManager",
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        raise NotImplementedError("SourceProvider.search() must be implemented by subclasses")


@dataclass(slots=True)
class PaperGroup:
    """Grouped resources for one paper component/session/year/source combination."""

    subject_code: str
    subject_name: str
    session: str
    year: str
    component: str
    source: str
    primary_docs: Dict[str, PaperResource] = field(default_factory=dict)
    resources: Dict[str, PaperResource] = field(default_factory=dict)
    locked_variant: Optional[str] = None
    is_specimen: bool = False

    def all_documents(self, include_resources: bool = True) -> List[PaperResource]:
        order = ["QP", "SP_QP", "MS", "SP_MS", "ER", "GT", "IN", "MAP", "SF", "AU", "TN"]
        docs: List[PaperResource] = []
        for key in order:
            if key in self.primary_docs:
                docs.append(self.primary_docs[key])
            if include_resources and key in self.resources:
                docs.append(self.resources[key])
        if include_resources:
            for key in sorted(self.resources.keys()):
                if key not in order:
                    docs.append(self.resources[key])
        return docs

    def has_insert(self) -> bool:
        return "IN" in self.resources

    def has_source_files(self) -> bool:
        return "SF" in self.resources

    def has_audio(self) -> bool:
        return "AU" in self.resources

    def has_transcript(self) -> bool:
        return "TN" in self.resources

    def has_map(self) -> bool:
        return "MAP" in self.resources

    def to_result_item(self, resource: PaperResource) -> Dict:
        doc_type = {
            "QP": "QP",
            "SP_QP": "QP",
            "MS": "MS",
            "SP_MS": "MS",
            "ER": "ER",
            "GT": "GT",
            "IN": "IN",
            "SF": "SF",
            "AU": "AU",
            "TN": "TN",
            "MAP": "MAP",
        }.get(resource.kind, resource.kind)
        type_name = {
            "QP": "Question Paper",
            "SP_QP": "Specimen Question Paper",
            "MS": "Mark Scheme",
            "SP_MS": "Specimen Mark Scheme",
            "ER": "Examiner Report",
            "GT": "Grade Threshold",
            "IN": "Insert",
            "SF": "Source File",
            "AU": "Audio",
            "TN": "Transcript",
            "MAP": "Map",
        }.get(resource.kind, resource.kind)

        return {
            "subject": self.subject_name,
            "subject_code": self.subject_code,
            "year": self.year,
            "series": self.session,
            "component": str(self.component),
            "type": doc_type,
            "type_name": type_name,
            "filename": resource.filename,
            "url": resource.url,
            "direct_url": resource.direct_url,
            "viewer_url": resource.viewer_url,
            "open_url": resource.open_url,
            "download_url": resource.download_url,
            "resource_family": resource.resource_family,
            "resource_token": resource.resource_token,
            "extension": resource.extension,
            "downloaded": bool(resource.downloaded),
            "source": resource.source,
            "is_specimen": bool(self.is_specimen),
            "resource_kind": resource.kind,
            "locked_variant": self.locked_variant,
        }


@dataclass(slots=True)
class SearchResult:
    """Container for a completed or cached search result."""

    groups: List["PaperGroup"]
    status: str = "success"
    from_cache: bool = False
    cancelled: bool = False


class BestExamHelpProvider(SourceProvider):
    name = "bestexamhelp"

    def search(
        self,
        manager: "PaperSourceManager",
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        return manager._search_bestexamhelp(subject_code, year, series, component, doc_types)


class PapacambridgeProvider(SourceProvider):
    def __init__(self, source_name: str) -> None:
        self.name = str(source_name or "").strip()

    def search(
        self,
        manager: "PaperSourceManager",
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        return manager._search_papacambridge(subject_code, year, series, component, doc_types)


class GceGuideProvider(SourceProvider):
    name = "gceguide"

    def search(
        self,
        manager: "PaperSourceManager",
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        return manager._search_gceguide(subject_code, year, series, component, doc_types)


class DynamicPapersProvider(SourceProvider):
    name = "dynamicpapers"

    def search(
        self,
        manager: "PaperSourceManager",
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        return manager._search_dynamicpapers(subject_code, year, series, component, doc_types)


class PaperSourceManager:
    """Multi-source paper fetching with fallbacks."""

    PASTPAPERSCO_CANONICAL_UPLOAD_BASE = (
        "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload"
    )

    SOURCES: Dict[str, Dict] = {
        "bestexamhelp": {
            "base_url": "https://bestexamhelp.com/exam",
            "priority": 1,
            "levels": {
                "IGCSE": "cambridge-igcse",
                "A Level": "cambridge-international-a-level",
            },
        },
        "pastpapersco": {
            "base_url": PASTPAPERSCO_CANONICAL_UPLOAD_BASE,
            "upload_bases": [
                PASTPAPERSCO_CANONICAL_UPLOAD_BASE,
                "https://pastpapers.co/cie/files",
                "https://www.pastpapers.co/cie/files",
            ],
            "priority": 2,
        },
        "papacambridge": {
            # Legacy alias kept for backward compatibility only.
            "base_url": PASTPAPERSCO_CANONICAL_UPLOAD_BASE,
            "upload_bases": [
                PASTPAPERSCO_CANONICAL_UPLOAD_BASE,
                "https://pastpapers.co/cie/files",
                "https://www.pastpapers.co/cie/files",
            ],
            "priority": 7,
        },
        "gceguide": {
            "index_urls": {
                "IGCSE": "https://www.gceguide.cc/papers/cambridge-IGCSE/",
                "A Level": "https://www.gceguide.cc/papers/cambridge-a-level/",
            },
            "priority": 3,
        },
        "dynamicpapers": {
            "base_url": "https://dynamicpapers.com",
            "priority": 4,
        },
        "znotes": {
            "base_url": "https://znotes.org",
            "priority": 5,
        },
        "savemyexams": {
            "base_url": "https://www.savemyexams.co.uk",
            "priority": 6,
        },
    }

    _session = requests.Session()
    _default_session = _session
    _thread_sessions = threading.local()
    _gceguide_subject_cache: Dict[str, Dict[str, object]] = {}
    _source_pdf_catalog_cache: Dict[str, Dict[str, object]] = {}
    _papacambridge_subject_slug_cache: Dict[str, str] = {}
    _papacambridge_docs_cache: Dict[str, List[PapacambridgeDocRef]] = {}
    _url_pdf_probe_cache: Dict[str, Dict[str, object]] = {}
    _fm_variant_cache: Dict[str, Dict[str, object]] = {}
    _component_style_cache: Dict[str, Dict[str, object]] = {}
    _search_cache_l1: Dict[str, Dict[str, object]] = {}
    _pastpapersco_preferred_base: str = ""
    _session_headers_ready: bool = False
    _search_cache_loaded: bool = False
    _search_cache_dirty: bool = False
    _search_cache: Dict[str, Dict[str, object]] = {}
    _component_cache_loaded: bool = False
    _component_cache_dirty: bool = False
    _component_cache: Dict[str, Dict[str, object]] = {}
    _source_failure_state: Dict[str, Dict[str, float]] = {}
    _search_logger = get_search_logger()
    _search_logger_configured = False
    _active_queries: Dict[str, Dict[str, object]] = {}
    _active_queries_lock = threading.Lock()
    _url_probe_inflight: Dict[str, threading.Event] = {}
    _url_probe_inflight_lock = threading.Lock()
    _providers: Dict[str, "SourceProvider"] = {}

    REQUEST_TIMEOUT_SECONDS: int = 3
    PAPACAMBRIDGE_HEAD_TIMEOUT_SECONDS: float = 1.2
    PAPACAMBRIDGE_LISTING_TIMEOUT_SECONDS: float = 3.0
    ENABLE_PASTPAPERSCO_LISTING_FALLBACK: bool = True
    SEARCH_CACHE_TTL_SECONDS: int = 24 * 60 * 60
    SEARCH_CACHE_SUCCESS_TTL_SECONDS: int = 24 * 60 * 60
    SEARCH_CACHE_EMPTY_TTL_SECONDS: int = 90
    SEARCH_CACHE_ERROR_TTL_SECONDS: int = 45
    SEARCH_CACHE_FILE: str = cache_path("paper_search_cache.json")
    COMPONENT_CACHE_TTL_SECONDS: int = 24 * 60 * 60
    COMPONENT_CACHE_FILE: str = cache_path("available_components_cache.json")
    COMPONENT_DISCOVERY_TIMEOUT_SECONDS: float = 1.5
    URL_PROBE_POSITIVE_TTL_SECONDS: int = 8 * 60 * 60
    URL_PROBE_NEGATIVE_TTL_SECONDS: int = 10 * 60
    URL_PROBE_TRANSIENT_NEGATIVE_TTL_SECONDS: int = 60
    URL_PROBE_REQUEST_TIMEOUT_SECONDS: float = 1.6
    URL_PROBE_CACHE_MAX_ENTRIES: int = 20_000
    FM_VARIANT_CACHE_TTL_SECONDS: int = 6 * 60 * 60
    SEARCH_CACHE_L1_TTL_SECONDS: int = 10 * 60
    SEARCH_CACHE_L1_MAX_ENTRIES: int = 500
    SOURCE_PDF_CATALOG_POSITIVE_TTL_SECONDS: int = 20 * 60
    SOURCE_PDF_CATALOG_NEGATIVE_TTL_SECONDS: int = 90
    GCEGUIDE_SUBJECT_POSITIVE_TTL_SECONDS: int = 20 * 60
    GCEGUIDE_SUBJECT_NEGATIVE_TTL_SECONDS: int = 90
    SOURCE_SEARCH_MAX_WORKERS: int = 4
    SOURCE_SEARCH_RETRY_COUNT: int = 2
    SOURCE_FAILURE_COOLDOWN_SECONDS: float = 10.0
    SOURCE_FAILURE_COOLDOWN_THRESHOLD: int = 2
    BESTEXAMHELP_MAX_COMPONENT_PROBES: int = 4
    REQUEST_HEADERS: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/pdf,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://pastpapers.co/",
        "Connection": "keep-alive",
    }

    @classmethod
    def _get_source_provider(cls, source_name: str) -> Optional["SourceProvider"]:
        """Return a SourceProvider instance for the given source name."""
        key = str(source_name or "").strip()
        if not key:
            return None
        if not cls._providers:
            cls._providers = {
                "bestexamhelp": BestExamHelpProvider(),
                "pastpapersco": PapacambridgeProvider(source_name="pastpapersco"),
                "papacambridge": PapacambridgeProvider(source_name="papacambridge"),
                "gceguide": GceGuideProvider(),
                "dynamicpapers": DynamicPapersProvider(),
            }
        return cls._providers.get(key)

    @classmethod
    def _search_debug_enabled(cls) -> bool:
        raw = str(os.environ.get("PAST_PAPER_FINDER_DEBUG_SEARCH", "") or "").strip().lower()
        return raw in {"1", "true", "yes", "on", "debug"}

    @classmethod
    def _debug_log(cls, message: str) -> None:
        if cls._search_debug_enabled():
            print(message)

    @classmethod
    def _ensure_search_logger(cls, force: bool = False) -> None:
        if cls._search_logger_configured and not force:
            return
        enabled = True
        level = "INFO"
        try:
            search_cfg = ConfigManager.get_search_config()
            logging_cfg = search_cfg.get("logging", {}) if isinstance(search_cfg, dict) else {}
            if isinstance(logging_cfg, dict):
                enabled = bool(logging_cfg.get("enabled", True))
                level = str(logging_cfg.get("level", "INFO") or "INFO")
        except Exception:
            enabled = True
            level = "INFO"
        cls._search_logger = configure_search_logging(enabled=enabled, level=level)
        cls._search_logger_configured = True

    @classmethod
    def _log_event(cls, event: str, *, level: str = "info", **fields: object) -> None:
        cls._ensure_search_logger()
        payload: Dict[str, object] = {
            "event": str(event or "").strip(),
            "ts": cls._now_ts(),
        }
        for key, value in fields.items():
            payload[str(key)] = value
        text = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
        logger = cls._search_logger or get_search_logger()
        level_name = str(level or "info").strip().lower()
        log_fn = getattr(logger, level_name, logger.info)
        try:
            log_fn(text)
        except Exception:
            pass

    @classmethod
    def _search_runtime_config(cls) -> Dict[str, object]:
        defaults = {
            "fast_first_target_ms": 2500,
            "max_total_ms": 10000,
            "enable_background_enrichment": True,
            "stop_on_first_source_hit": True,
        }
        try:
            cfg = ConfigManager.get_search_config()
        except Exception:
            cfg = {}
        if not isinstance(cfg, dict):
            return defaults
        out = dict(defaults)
        try:
            out["fast_first_target_ms"] = max(500, int(cfg.get("fast_first_target_ms", 2500) or 2500))
        except Exception:
            out["fast_first_target_ms"] = 2500
        try:
            out["max_total_ms"] = max(int(out["fast_first_target_ms"]), int(cfg.get("max_total_ms", 10000) or 10000))
        except Exception:
            out["max_total_ms"] = 10000
        out["enable_background_enrichment"] = bool(cfg.get("enable_background_enrichment", True))
        # Keep fast-first UX deterministic: once any valid paper is found, stop source scanning.
        out["stop_on_first_source_hit"] = True
        return out

    @classmethod
    def _request_fingerprint(
        cls,
        *,
        subject_code: str,
        series_list: List[str],
        components: List[str],
        years: List[str],
        doc_types: List[str],
        level: str,
    ) -> str:
        query = SearchQuery(
            subject_code=str(subject_code or "").strip(),
            level=str(level or "").strip(),
            series_list=list(series_list or []),
            components=list(components or []),
            years=list(years or []),
            doc_types=list(doc_types or []),
        )
        return query.fingerprint()

    @classmethod
    def _prune_active_queries_locked(cls, now: float) -> None:
        stale_keys: List[str] = []
        for key, entry in cls._active_queries.items():
            if not isinstance(entry, dict):
                stale_keys.append(key)
                continue
            if not bool(entry.get("done", False)):
                started_at = cls._coerce_timestamp(entry.get("started_at", 0.0))
                if started_at <= 0.0 or (now - started_at) > 30.0:
                    stale_keys.append(key)
                continue
            completed_at = cls._coerce_timestamp(entry.get("completed_at", 0.0))
            if completed_at <= 0.0 or (now - completed_at) > 20.0:
                stale_keys.append(key)
        for key in stale_keys:
            cls._active_queries.pop(key, None)

    @classmethod
    def _join_or_acquire_active_query(
        cls,
        query_key: str,
        *,
        wait_seconds: float,
    ) -> Tuple[bool, Optional[List["PaperGroup"]]]:
        key = str(query_key or "")
        if not key:
            return (True, None)
        now = cls._now_ts()
        with cls._active_queries_lock:
            cls._prune_active_queries_locked(now)
            existing = cls._active_queries.get(key)
            if isinstance(existing, dict):
                event = existing.get("event")
                if isinstance(event, threading.Event):
                    wait_event = event
                else:
                    wait_event = threading.Event()
                    existing["event"] = wait_event
            else:
                wait_event = threading.Event()
                cls._active_queries[key] = {
                    "event": wait_event,
                    "done": False,
                    "started_at": now,
                }
                return (True, None)
        # Join in-flight request.
        wait_event.wait(timeout=max(0.1, float(wait_seconds)))
        with cls._active_queries_lock:
            entry = cls._active_queries.get(key)
            if isinstance(entry, dict) and bool(entry.get("done", False)):
                result = entry.get("result")
                if isinstance(result, list):
                    return (False, list(result))
        return (False, None)

    @classmethod
    def _complete_active_query(cls, query_key: str, result: List["PaperGroup"]) -> None:
        key = str(query_key or "")
        if not key:
            return
        event: Optional[threading.Event] = None
        with cls._active_queries_lock:
            entry = cls._active_queries.get(key)
            if not isinstance(entry, dict):
                entry = {}
                cls._active_queries[key] = entry
            entry["result"] = list(result or [])
            entry["done"] = True
            entry["completed_at"] = cls._now_ts()
            maybe_event = entry.get("event")
            if isinstance(maybe_event, threading.Event):
                event = maybe_event
        if event is not None:
            event.set()

    @classmethod
    def _source_is_cooling_down(cls, source_name: str) -> bool:
        state = cls._source_failure_state.get(str(source_name or ""))
        if not isinstance(state, dict):
            return False
        cooldown_until = cls._coerce_timestamp(state.get("cooldown_until", 0.0))
        if cooldown_until <= 0.0:
            return False
        now = cls._now_ts()
        if cooldown_until <= now:
            state["cooldown_until"] = 0.0
            return False
        return True

    @classmethod
    @synchronized
    def _record_source_success(cls, source_name: str) -> None:
        token = str(source_name or "")
        if not token:
            return
        cls._source_failure_state[token] = {"failures": 0.0, "cooldown_until": 0.0}

    @classmethod
    @synchronized
    def _record_source_failure(cls, source_name: str, transient: bool) -> None:
        token = str(source_name or "")
        if not token:
            return
        state = cls._source_failure_state.get(token, {"failures": 0.0, "cooldown_until": 0.0})
        failures = float(state.get("failures", 0.0) or 0.0) + 1.0
        state["failures"] = failures
        if transient and failures >= float(cls.SOURCE_FAILURE_COOLDOWN_THRESHOLD):
            state["cooldown_until"] = cls._now_ts() + float(cls.SOURCE_FAILURE_COOLDOWN_SECONDS)
        cls._source_failure_state[token] = state

    @classmethod
    def _acquire_url_probe_slot(cls, url: str) -> Tuple[bool, Optional[threading.Event]]:
        target = str(url or "").strip()
        if not target:
            return (False, None)
        with cls._url_probe_inflight_lock:
            event = cls._url_probe_inflight.get(target)
            if isinstance(event, threading.Event):
                return (False, event)
            new_event = threading.Event()
            cls._url_probe_inflight[target] = new_event
            return (True, new_event)

    @classmethod
    def _release_url_probe_slot(cls, url: str) -> None:
        target = str(url or "").strip()
        if not target:
            return
        event: Optional[threading.Event] = None
        with cls._url_probe_inflight_lock:
            maybe_event = cls._url_probe_inflight.pop(target, None)
            if isinstance(maybe_event, threading.Event):
                event = maybe_event
        if event is not None:
            event.set()

    @staticmethod
    def _now_ts() -> float:
        return time.time()

    @staticmethod
    def _coerce_timestamp(value: object) -> float:
        try:
            parsed = float(value or 0.0)
        except Exception:
            parsed = 0.0
        return parsed if parsed > 0.0 else 0.0

    @classmethod
    @synchronized
    def _prune_cache_by_size(cls, cache: Dict[str, Dict[str, object]], max_entries: int) -> None:
        target = max(32, int(max_entries or 0))
        if len(cache) <= target:
            return
        ordered = sorted(
            cache.items(),
            key=lambda row: cls._coerce_timestamp(
                row[1].get("checked_at")
                if isinstance(row[1], dict)
                else 0.0
            ),
        )
        trim = max(0, len(cache) - target)
        for stale_key, _ in ordered[:trim]:
            cache.pop(stale_key, None)

    @classmethod
    @synchronized
    def _url_probe_cache_get(cls, url: str) -> Optional[bool]:
        target = str(url or "").strip()
        if not target:
            return None
        entry = cls._url_pdf_probe_cache.get(target)
        if isinstance(entry, bool):
            # Backward-compatibility with in-memory callers from earlier builds.
            exists = bool(entry)
            cls._url_pdf_probe_cache[target] = {
                "exists": exists,
                "checked_at": cls._now_ts(),
                "source_status": "legacy",
            }
            return exists
        if not isinstance(entry, dict):
            return None
        exists = bool(entry.get("exists", False))
        checked_at = cls._coerce_timestamp(entry.get("checked_at", 0.0))
        if checked_at <= 0.0:
            cls._url_pdf_probe_cache.pop(target, None)
            return None
        ttl_seconds = (
            int(cls.URL_PROBE_POSITIVE_TTL_SECONDS)
            if exists
            else int(cls.URL_PROBE_NEGATIVE_TTL_SECONDS)
        )
        if not exists:
            source_status = str(entry.get("source_status", "")).lower()
            if "error" in source_status or "timeout" in source_status:
                ttl_seconds = min(ttl_seconds, int(cls.URL_PROBE_TRANSIENT_NEGATIVE_TTL_SECONDS))
        if (cls._now_ts() - checked_at) > max(1, ttl_seconds):
            cls._url_pdf_probe_cache.pop(target, None)
            return None
        return exists

    @classmethod
    @synchronized
    def _url_probe_cache_put(cls, url: str, exists: bool, source_status: str = "") -> None:
        target = str(url or "").strip()
        if not target:
            return
        cls._url_pdf_probe_cache[target] = {
            "exists": bool(exists),
            "checked_at": cls._now_ts(),
            "source_status": str(source_status or ""),
        }
        cls._prune_cache_by_size(cls._url_pdf_probe_cache, cls.URL_PROBE_CACHE_MAX_ENTRIES)

    @classmethod
    @synchronized
    def _url_probe_cache_drop(cls, url: str) -> None:
        target = str(url or "").strip()
        if not target:
            return
        cls._url_pdf_probe_cache.pop(target, None)

    @classmethod
    def _fm_variant_cache_key(
        cls,
        subject_code: str,
        papers: List[str],
        years: List[str],
    ) -> str:
        payload = {
            "subject_code": str(subject_code or "").strip(),
            "papers": sorted({str(p).strip() for p in papers if str(p).strip()}),
            "years": sorted({str(y).strip() for y in years if str(y).strip()}),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    @synchronized
    def _fm_variant_cache_get(cls, key: str) -> Optional[str]:
        entry = cls._fm_variant_cache.get(str(key or ""))
        if not isinstance(entry, dict):
            return None
        created_at = cls._coerce_timestamp(entry.get("checked_at", 0.0))
        if created_at <= 0.0:
            cls._fm_variant_cache.pop(str(key or ""), None)
            return None
        ttl = max(30, int(cls.FM_VARIANT_CACHE_TTL_SECONDS))
        if (cls._now_ts() - created_at) > ttl:
            cls._fm_variant_cache.pop(str(key or ""), None)
            return None
        variant = str(entry.get("variant", "") or "").strip()
        return variant if variant in {"1", "2", "3"} else None

    @classmethod
    @synchronized
    def _fm_variant_cache_put(cls, key: str, variant: str) -> None:
        token = str(variant or "").strip()
        if token not in {"1", "2", "3"}:
            return
        cls._fm_variant_cache[str(key or "")] = {
            "variant": token,
            "checked_at": cls._now_ts(),
        }
        cls._prune_cache_by_size(cls._fm_variant_cache, 1500)

    PAPACAMBRIDGE_INDEX_URLS: Dict[str, str] = {
        "IGCSE": "https://pastpapers.co/cie/?dir=IGCSE",
        "A Level": "https://pastpapers.co/cie/?dir=A-Level",
    }

    PAPACAMBRIDGE_SESSION_SLUGS: Dict[str, str] = {
        "MJ": "may-june",
        "ON": "oct-nov",
        "FM": "march",
    }

    TOKEN_TO_FAMILY: Dict[str, str] = {
        "in": "INSERT",
        "sf": "SOURCE_FILE",  # extension-specific override applies below
        "tn": "TRANSCRIPT",
        "qr": "INSERT",
        "rp": "INSERT",
        "map": "MAP",
    }

    FAMILY_TO_KIND: Dict[str, str] = {
        "INSERT": "IN",
        "SOURCE_FILE": "SF",
        "AUDIO": "AU",
        "TRANSCRIPT": "TN",
        "MAP": "MAP",
    }

    SUBJECT_RESOURCE_POLICIES = {
        "0417": {"families": {"SOURCE_FILE"}, "papers": {2, 3}},
        "0450": {"families": {"INSERT"}, "papers": {2}},
        "0500": {"families": {"INSERT"}},
    }

    BESTEXAMHELP_IGCSE_CODES: set[str] = set(SubjectDatabase.BESTEXAMHELP_IGCSE_CODES)
    PAPER_NAME_OVERRIDES = {
        "0580": {
            "1": "Core Short Answer",
            "2": "Extended Short Answer",
            "3": "Core Structured",
            "4": "Extended Structured",
        },
        "0607": {
            "1": "Core Non-Calculator",
            "2": "Extended Non-Calculator",
            "3": "Core Calculator",
            "4": "Extended Calculator",
        },
        "0620": {
            "1": "Multiple Choice (Core)",
            "2": "Multiple Choice (Extended)",
            "3": "Theory (Core)",
            "4": "Theory (Extended)",
            "5": "Practical Test",
            "6": "Alternative to Practical",
        },
        "0610": {
            "1": "Multiple Choice (Core)",
            "2": "Multiple Choice (Extended)",
            "3": "Theory (Core)",
            "4": "Theory (Extended)",
            "5": "Practical Test",
            "6": "Alternative to Practical",
        },
        "0625": {
            "1": "Multiple Choice (Core)",
            "2": "Multiple Choice (Extended)",
            "3": "Theory (Core)",
            "4": "Theory (Extended)",
            "5": "Practical Test",
            "6": "Alternative to Practical",
        },
        "0500": {
            "1": "Reading",
            "2": "Writing",
            "3": "Directed Writing and Composition",
            "4": "Coursework Portfolio",
        },
    }

    @classmethod
    def _ensure_session(cls) -> requests.Session:
        if cls._session is not cls._default_session:
            return cls._session  # Explicitly injected transport (tests / embedding).
        session = getattr(cls._thread_sessions, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(dict(cls.REQUEST_HEADERS))
            cls._thread_sessions.session = session
        return session

    @classmethod
    def _resolve_timeout(cls, timeout: Optional[float] = None) -> float:
        default_timeout = float(cls.REQUEST_TIMEOUT_SECONDS)
        if timeout is None:
            return default_timeout
        try:
            value = float(timeout)
        except Exception:
            return default_timeout
        return max(1.0, min(value, default_timeout))

    @classmethod
    def _http_get(
        cls,
        url: str,
        *,
        timeout: Optional[float] = None,
        allow_redirects: bool = True,
        stream: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        merged_headers = dict(cls.REQUEST_HEADERS)
        if headers:
            merged_headers.update({k: str(v) for k, v in headers.items() if v is not None})
        target = str(url or "").strip()
        started = time.perf_counter()
        response = cls._ensure_session().get(
            target,
            timeout=cls._resolve_timeout(timeout),
            allow_redirects=allow_redirects,
            stream=stream,
            headers=merged_headers,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cls._debug_log(
            f"[http:get] {target} -> {getattr(response, 'status_code', '?')} "
            f"in {elapsed_ms:.0f} ms"
        )
        return response

    @classmethod
    def _http_head(
        cls,
        url: str,
        *,
        timeout: Optional[float] = None,
        allow_redirects: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        merged_headers = dict(cls.REQUEST_HEADERS)
        if headers:
            merged_headers.update({k: str(v) for k, v in headers.items() if v is not None})
        target = str(url or "").strip()
        started = time.perf_counter()
        response = cls._ensure_session().head(
            target,
            timeout=cls._resolve_timeout(timeout),
            allow_redirects=allow_redirects,
            headers=merged_headers,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        cls._debug_log(
            f"[http:head] {target} -> {getattr(response, 'status_code', '?')} "
            f"in {elapsed_ms:.0f} ms"
        )
        return response

    @classmethod
    def _http_get_text(cls, url: str, *, timeout: Optional[float] = None) -> str:
        response = cls._http_get(url, timeout=timeout, allow_redirects=True, stream=False)
        try:
            try:
                status_code = int(getattr(response, "status_code", 200))
            except Exception:
                status_code = 200
            if status_code >= 400:
                return ""
            return str(response.text or "")
        finally:
            cls._safe_close_response(response)

    @staticmethod
    def _safe_close_response(response: object) -> None:
        close_fn = getattr(response, "close", None)
        if not callable(close_fn):
            return
        try:
            close_fn()
        except Exception:
            pass

    @classmethod
    def _optimize_source_order_for_subject(
        cls,
        subject_code: str,
        source_order: List[str],
    ) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        for source in source_order:
            token = str(source or "").strip()
            if not token or token not in cls.SOURCES or token in seen:
                continue
            seen.add(token)
            ordered.append(token)

        code = str(subject_code or "").strip()
        mapped_sources = SubjectDatabase.SUBJECT_SOURCE_MAP.get(code, [])
        mapped_ordered: List[str] = []
        mapped_seen: set[str] = set()
        for source in mapped_sources:
            token = str(source or "").strip()
            if not token or token not in cls.SOURCES or token in mapped_seen:
                continue
            mapped_seen.add(token)
            mapped_ordered.append(token)
        if mapped_ordered:
            ordered = list(mapped_ordered)

        availability = SubjectDatabase.get_subject_availability(code)
        if (
            code
            and bool(availability.get("verified", False))
            and isinstance(availability.get("sources"), list)
        ):
            verified_sources = [s for s in availability["sources"] if str(s).strip() in cls.SOURCES]
            if verified_sources:
                verified_first = [s for s in verified_sources if s in ordered]
                others = [s for s in ordered if s not in verified_first]
                ordered = verified_first + others

        if "bestexamhelp" in ordered:
            if code and code in SubjectDatabase.BESTEXAMHELP_SUPPORTED_CODES:
                ordered = ["bestexamhelp"] + [source for source in ordered if source != "bestexamhelp"]
            elif code and code not in SubjectDatabase.BESTEXAMHELP_SUPPORTED_CODES:
                ordered = [source for source in ordered if source != "bestexamhelp"] + ["bestexamhelp"]
        return ordered

    @classmethod
    def _runtime_source_order(
        cls,
        subject_code: str,
        source_order: List[str],
    ) -> List[str]:
        code = str(subject_code or "").strip()
        default_runtime_order = [str(s) for s in source_order if str(s) in cls.SOURCES]
        optimized = cls._optimize_source_order_for_subject(code, default_runtime_order)
        if not optimized:
            return optimized

        reordered: List[str] = list(optimized)

        # Apply the proven French-foreign routing globally: pastpapers first, then papacambridge.
        preferred_front: List[str] = []
        for source in ("pastpapersco", "papacambridge"):
            if source in reordered:
                reordered.remove(source)
                preferred_front.append(source)
            elif source in cls.SOURCES:
                preferred_front.append(source)
        if preferred_front:
            reordered = preferred_front + reordered
        # Avoid BestExamHelp-only lockups by adding practical runtime fallbacks.
        if len(optimized) == 1 and optimized[0] == "bestexamhelp":
            for source in ("pastpapersco", "gceguide", "dynamicpapers", "papacambridge"):
                if source in cls.SOURCES and source not in reordered:
                    reordered.append(source)
        deduped: List[str] = []
        seen: set[str] = set()
        for source in reordered:
            if source in seen:
                continue
            seen.add(source)
            deduped.append(source)
        return deduped

    @classmethod
    def _normalize_requested_doc_types(cls, doc_types: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for raw in doc_types or []:
            token = str(raw or "").strip().upper()
            if token == "P":
                token = "QP"
            if token not in {"QP", "MS", "GT"}:
                continue
            if token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    @classmethod
    def _result_doc_type(cls, item: Dict) -> str:
        token = str(item.get("type", "")).strip().upper()
        if token == "P":
            return "QP"
        return token

    @classmethod
    @synchronized
    def _search_cache_key(
        cls,
        subject_code: str,
        series_list: List[str],
        components: List[str],
        years: List[str],
        doc_types: List[str],
        fm_locked_variant: Optional[str],
        series_component_map: Optional[Dict[str, List[str]]],
    ) -> str:
        normalized_series_map: Dict[str, List[str]] = {}
        if series_component_map:
            for key, values in series_component_map.items():
                series_code = str(key or "").strip().upper()
                if not series_code:
                    continue
                normalized_series_map[series_code] = [str(v).strip() for v in values or [] if str(v).strip()]

        payload = {
            "v": 2,
            "subject_code": str(subject_code or "").strip(),
            "series": [str(s).strip().upper() for s in series_list or [] if str(s).strip()],
            "components": [str(c).strip() for c in components or [] if str(c).strip()],
            "years": [str(y).strip() for y in years or [] if str(y).strip()],
            "doc_types": cls._normalize_requested_doc_types(doc_types or []),
            "fm_locked_variant": str(fm_locked_variant or "").strip(),
            "series_component_map": normalized_series_map,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    @synchronized
    def _search_cache_key_for_query(
        cls,
        query: SearchQuery,
        *,
        fm_locked_variant: Optional[str],
        series_component_map: Optional[Dict[str, List[str]]],
    ) -> str:
        """Build a cache key from a normalized SearchQuery."""
        return cls._search_cache_key(
            subject_code=query.subject_code,
            series_list=query.series_list,
            components=query.components,
            years=query.years,
            doc_types=query.doc_types,
            fm_locked_variant=fm_locked_variant,
            series_component_map=series_component_map,
        )

    @classmethod
    @synchronized
    def _search_cache_get_for_query(
        cls,
        query: SearchQuery,
        *,
        fm_locked_variant: Optional[str],
        series_component_map: Optional[Dict[str, List[str]]],
    ) -> Optional[SearchResult]:
        """Wrapper that returns a structured SearchResult for a given query."""
        cache_key = cls._search_cache_key_for_query(
            query,
            fm_locked_variant=fm_locked_variant,
            series_component_map=series_component_map,
        )
        groups = cls._search_cache_get(cache_key)
        if groups is None:
            return None
        status = "success" if groups else "empty"
        return SearchResult(groups=list(groups), status=status, from_cache=True, cancelled=False)

    @classmethod
    @synchronized
    def _search_cache_put_for_query(
        cls,
        query: SearchQuery,
        *,
        fm_locked_variant: Optional[str],
        series_component_map: Optional[Dict[str, List[str]]],
        result: SearchResult,
    ) -> None:
        """Store a SearchResult for a given query into both cache tiers."""
        cache_key = cls._search_cache_key_for_query(
            query,
            fm_locked_variant=fm_locked_variant,
            series_component_map=series_component_map,
        )
        cls._search_cache_put(cache_key, result.groups, status=result.status)

    @classmethod
    @synchronized
    def _search_cache_ttl_for_status(cls, status: str) -> int:
        token = str(status or "success").strip().lower()
        if token == "empty":
            return max(30, int(cls.SEARCH_CACHE_EMPTY_TTL_SECONDS))
        if token == "error":
            return max(20, int(cls.SEARCH_CACHE_ERROR_TTL_SECONDS))
        return max(60, int(cls.SEARCH_CACHE_SUCCESS_TTL_SECONDS))

    @classmethod
    @synchronized
    def _load_search_cache(cls) -> None:
        if cls._search_cache_loaded:
            return
        cls._search_cache_loaded = True
        cls._search_cache_dirty = False
        cls._search_cache = {}
        try:
            with open(
                cls.SEARCH_CACHE_FILE,
                "r",
                encoding="utf-8",
                buffering=file_buffer_size_bytes(),
            ) as handle:
                payload = json.load(handle)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return
        for key, value in entries.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            cls._search_cache[key] = value

    @classmethod
    @synchronized
    def _save_search_cache(cls) -> None:
        if not cls._search_cache_loaded or not cls._search_cache_dirty:
            return
        try:
            atomic_write_json(cls.SEARCH_CACHE_FILE, {"version": 1, "saved_at": time.time(), "entries": cls._search_cache})
            cls._search_cache_dirty = False
        except (OSError, ValueError, TypeError):
            cls._search_logger.exception("Could not save cache")

    @classmethod
    @synchronized
    def _prune_expired_search_cache(cls) -> None:
        now = time.time()
        keys_to_delete: List[str] = []
        for key, entry in cls._search_cache.items():
            if not isinstance(entry, dict):
                keys_to_delete.append(key)
                continue
            try:
                created_at = float(entry.get("timestamp", 0.0) or 0.0)
            except Exception:
                created_at = 0.0
            status = str(entry.get("status", "success") or "success").strip().lower()
            ttl = cls._search_cache_ttl_for_status(status)
            if created_at <= 0 or (now - created_at) > ttl:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            cls._search_cache.pop(key, None)
        if keys_to_delete:
            cls._search_cache_dirty = True

    @staticmethod
    def _serialize_resource(resource: PaperResource) -> Dict[str, object]:
        return {
            "kind": str(resource.kind or ""),
            "filename": str(resource.filename or ""),
            "url": str(resource.url or ""),
            "source": str(resource.source or ""),
            "downloaded": bool(resource.downloaded),
            "direct_url": str(resource.direct_url or ""),
            "viewer_url": str(resource.viewer_url or ""),
            "open_url": str(resource.open_url or ""),
            "download_url": str(resource.download_url or ""),
            "resource_family": str(resource.resource_family or ""),
            "resource_token": str(resource.resource_token or ""),
            "extension": str(resource.extension or ""),
        }

    @classmethod
    def _deserialize_resource(cls, data: Dict[str, object]) -> PaperResource:
        return PaperResource(
            kind=str(data.get("kind", "") or ""),
            filename=str(data.get("filename", "") or ""),
            url=str(data.get("url", "") or ""),
            source=str(data.get("source", "") or ""),
            downloaded=bool(data.get("downloaded", False)),
            direct_url=str(data.get("direct_url", "") or ""),
            viewer_url=str(data.get("viewer_url", "") or ""),
            open_url=str(data.get("open_url", "") or ""),
            download_url=str(data.get("download_url", "") or ""),
            resource_family=str(data.get("resource_family", "") or ""),
            resource_token=str(data.get("resource_token", "") or ""),
            extension=str(data.get("extension", "") or ""),
        )

    @classmethod
    def _serialize_groups(cls, groups: List[PaperGroup]) -> List[Dict[str, object]]:
        out: List[Dict[str, object]] = []
        for group in groups:
            primary_docs = {
                str(kind): cls._serialize_resource(resource)
                for kind, resource in (group.primary_docs or {}).items()
                if isinstance(resource, PaperResource)
            }
            resources = {
                str(kind): cls._serialize_resource(resource)
                for kind, resource in (group.resources or {}).items()
                if isinstance(resource, PaperResource)
            }
            out.append(
                {
                    "subject_code": str(group.subject_code or ""),
                    "subject_name": str(group.subject_name or ""),
                    "session": str(group.session or ""),
                    "year": str(group.year or ""),
                    "component": str(group.component or ""),
                    "source": str(group.source or ""),
                    "locked_variant": str(group.locked_variant or ""),
                    "is_specimen": bool(group.is_specimen),
                    "primary_docs": primary_docs,
                    "resources": resources,
                }
            )
        return out

    @classmethod
    def _deserialize_groups(cls, data: object) -> List[PaperGroup]:
        rows = data if isinstance(data, list) else []
        groups: List[PaperGroup] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            primary_docs_raw = row.get("primary_docs", {})
            resources_raw = row.get("resources", {})
            primary_docs: Dict[str, PaperResource] = {}
            resources: Dict[str, PaperResource] = {}
            if isinstance(primary_docs_raw, dict):
                for kind, payload in primary_docs_raw.items():
                    if not isinstance(payload, dict):
                        continue
                    primary_docs[str(kind)] = cls._deserialize_resource(payload)
            if isinstance(resources_raw, dict):
                for kind, payload in resources_raw.items():
                    if not isinstance(payload, dict):
                        continue
                    resources[str(kind)] = cls._deserialize_resource(payload)
            groups.append(
                PaperGroup(
                    subject_code=str(row.get("subject_code", "") or ""),
                    subject_name=str(row.get("subject_name", "") or ""),
                    session=str(row.get("session", "") or ""),
                    year=str(row.get("year", "") or ""),
                    component=str(row.get("component", "") or ""),
                    source=str(row.get("source", "") or ""),
                    primary_docs=primary_docs,
                    resources=resources,
                    locked_variant=(str(row.get("locked_variant", "") or "") or None),
                    is_specimen=bool(row.get("is_specimen", False)),
                )
            )
        return groups

    @classmethod
    @synchronized
    def _search_cache_l1_prune(cls) -> None:
        now = cls._now_ts()
        stale_keys: List[str] = []
        for key, entry in cls._search_cache_l1.items():
            if not isinstance(entry, dict):
                stale_keys.append(key)
                continue
            created_at = cls._coerce_timestamp(entry.get("timestamp", 0.0))
            status = str(entry.get("status", "success") or "success").strip().lower()
            ttl = min(
                max(30, int(cls.SEARCH_CACHE_L1_TTL_SECONDS)),
                cls._search_cache_ttl_for_status(status),
            )
            if created_at <= 0.0 or (now - created_at) > ttl:
                stale_keys.append(key)
        for key in stale_keys:
            cls._search_cache_l1.pop(key, None)
        cls._prune_cache_by_size(cls._search_cache_l1, cls.SEARCH_CACHE_L1_MAX_ENTRIES)

    @classmethod
    @synchronized
    def _search_cache_get(cls, key: str) -> Optional[List[PaperGroup]]:
        query_key = str(key or "")
        cls._search_cache_l1_prune()
        l1_entry = cls._search_cache_l1.get(query_key)
        if isinstance(l1_entry, dict) and isinstance(l1_entry.get("groups"), list):
            status = str(l1_entry.get("status", "success") or "success").strip().lower()
            groups = cls._deserialize_groups(l1_entry.get("groups"))
            cls._log_event(
                "cache.hit",
                tier="l1",
                status=status,
                key=hash(query_key) & 0xFFFF_FFFF,
                groups=len(groups),
            )
            cls._debug_log(
                "[sources] L1 cache hit for query "
                f"key={hash(query_key) & 0xFFFF_FFFF:x} groups={len(groups)}"
            )
            return groups

        cls._load_search_cache()
        cls._prune_expired_search_cache()
        entry = cls._search_cache.get(query_key)
        if not isinstance(entry, dict):
            cls._log_event("cache.miss", tier="disk", key=hash(query_key) & 0xFFFF_FFFF)
            cls._save_search_cache()
            return None
        if "groups" not in entry:
            cls._log_event("cache.miss", tier="disk", key=hash(query_key) & 0xFFFF_FFFF)
            cls._save_search_cache()
            return None
        status = str(entry.get("status", "success") or "success").strip().lower()
        groups = cls._deserialize_groups(entry.get("groups"))
        cls._search_cache_l1[query_key] = {
            "timestamp": cls._now_ts(),
            "status": status,
            "groups": cls._serialize_groups(groups),
        }
        cls._search_cache_l1_prune()
        cls._save_search_cache()
        cls._log_event(
            "cache.hit",
            tier="disk",
            status=status,
            key=hash(query_key) & 0xFFFF_FFFF,
            groups=len(groups),
        )
        cls._debug_log(
            "[sources] cache hit for query "
            f"key={hash(query_key) & 0xFFFF_FFFF:x} groups={len(groups)}"
        )
        return groups

    @classmethod
    @synchronized
    def _search_cache_put(cls, key: str, groups: List[PaperGroup], status: str = "success") -> None:
        query_key = str(key or "")
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"success", "empty", "error"}:
            normalized_status = "success" if groups else "empty"
        serialized_groups = cls._serialize_groups(groups)
        cls._search_cache_l1[query_key] = {
            "timestamp": cls._now_ts(),
            "status": normalized_status,
            "groups": serialized_groups,
        }
        cls._search_cache_l1_prune()

        cls._load_search_cache()
        cls._prune_expired_search_cache()
        cls._search_cache[query_key] = {
            "timestamp": cls._now_ts(),
            "status": normalized_status,
            "groups": serialized_groups,
        }
        if len(cls._search_cache) > 5000:
            oldest = sorted(
                cls._search_cache.items(),
                key=lambda item: float(item[1].get("timestamp", 0.0) or 0.0)
                if isinstance(item[1], dict)
                else 0.0,
            )
            for stale_key, _ in oldest[: max(0, len(cls._search_cache) - 5000)]:
                cls._search_cache.pop(stale_key, None)
        cls._search_cache_dirty = True
        cls._save_search_cache()
        cls._log_event(
            "cache.write",
            status=normalized_status,
            key=hash(query_key) & 0xFFFF_FFFF,
            groups=len(groups),
        )

    @classmethod
    @synchronized
    def invalidate_search_cache(cls, subject_code: Optional[str] = None) -> int:
        """Remove cache entries, optionally filtered by subject. Returns count removed."""
        cls._load_search_cache()
        if subject_code is None:
            removed = len(cls._search_cache)
            cls._search_cache.clear()
            cls._search_cache_l1.clear()
        else:
            code = str(subject_code or "").strip()
            removed = 0
            keys_to_drop = [
                k for k in cls._search_cache
                if isinstance(k, str) and f'"subject_code":"{code}"' in k
            ]
            for k in keys_to_drop:
                cls._search_cache.pop(k, None)
                cls._search_cache_l1.pop(k, None)
                removed += 1
        if removed:
            cls._search_cache_dirty = True
            cls._save_search_cache()
        return removed

    @staticmethod
    @synchronized
    def _component_cache_key(subject_code: str, series: str, year: str) -> str:
        return json.dumps(
            {
                "subject_code": str(subject_code or "").strip(),
                "series": str(series or "").strip().upper(),
                "year": str(year or "").strip(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    @synchronized
    def _load_component_cache(cls) -> None:
        if cls._component_cache_loaded:
            return
        cls._component_cache_loaded = True
        cls._component_cache_dirty = False
        cls._component_cache = {}
        try:
            with open(
                cls.COMPONENT_CACHE_FILE,
                "r",
                encoding="utf-8",
                buffering=file_buffer_size_bytes(),
            ) as handle:
                payload = json.load(handle)
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            return
        for key, value in entries.items():
            if isinstance(key, str) and isinstance(value, dict):
                cls._component_cache[key] = value

    @classmethod
    @synchronized
    def _save_component_cache(cls) -> None:
        if not cls._component_cache_loaded or not cls._component_cache_dirty:
            return
        try:
            atomic_write_json(cls.COMPONENT_CACHE_FILE, {"version": 1, "saved_at": time.time(), "entries": cls._component_cache})
            cls._component_cache_dirty = False
        except (OSError, ValueError, TypeError):
            cls._search_logger.exception("Could not save cache")

    @classmethod
    @synchronized
    def _prune_component_cache(cls) -> None:
        now = time.time()
        ttl = max(60, int(cls.COMPONENT_CACHE_TTL_SECONDS))
        stale_keys: List[str] = []
        for key, entry in cls._component_cache.items():
            if not isinstance(entry, dict):
                stale_keys.append(key)
                continue
            try:
                created_at = float(entry.get("timestamp", 0.0) or 0.0)
            except Exception:
                created_at = 0.0
            if created_at <= 0 or (now - created_at) > ttl:
                stale_keys.append(key)
        for key in stale_keys:
            cls._component_cache.pop(key, None)
        if stale_keys:
            cls._component_cache_dirty = True

    @classmethod
    @synchronized
    def _component_cache_get(cls, key: str) -> Optional[List[Dict[str, object]]]:
        cls._load_component_cache()
        cls._prune_component_cache()
        entry = cls._component_cache.get(str(key or ""))
        if not isinstance(entry, dict):
            cls._save_component_cache()
            return None
        rows = entry.get("components")
        if not isinstance(rows, list):
            cls._save_component_cache()
            return None
        out: List[Dict[str, object]] = []
        for row in rows:
            if isinstance(row, dict):
                out.append(dict(row))
        cls._save_component_cache()
        return out

    @classmethod
    @synchronized
    def _component_cache_put(cls, key: str, components: List[Dict[str, object]]) -> None:
        cls._load_component_cache()
        cls._prune_component_cache()
        cls._component_cache[str(key or "")] = {
            "timestamp": time.time(),
            "components": [dict(row) for row in components if isinstance(row, dict)],
        }
        if len(cls._component_cache) > 2000:
            oldest = sorted(
                cls._component_cache.items(),
                key=lambda item: float(item[1].get("timestamp", 0.0) or 0.0)
                if isinstance(item[1], dict)
                else 0.0,
            )
            for stale_key, _ in oldest[: max(0, len(cls._component_cache) - 2000)]:
                cls._component_cache.pop(stale_key, None)
        cls._component_cache_dirty = True
        cls._save_component_cache()

    @classmethod
    def _coerce_full_year_text(cls, year: object) -> str:
        raw = str(year or "").strip()
        if not raw:
            return ""
        if len(raw) == 2 and raw.isdigit():
            return f"20{raw}"
        match = re.search(r"(20\d{2})", raw)
        if match:
            return match.group(1)
        return raw

    @staticmethod
    def _component_sort_key(value: object) -> Tuple[int, str]:
        raw = str(value or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits.isdigit():
            return (int(digits), raw)
        return (999, raw)

    @classmethod
    def _candidate_paper_numbers(cls, subject_code: str) -> List[str]:
        code = str(subject_code or "").strip()
        allowed = ComponentsDatabase.COMPONENTS.get(code, [])
        papers: set[str] = set()
        for component in allowed:
            paper = cls._papacambridge_component_paper(str(component))
            if paper and paper.isdigit():
                papers.add(paper)
        if not papers:
            papers = {"1", "2", "3", "4", "5", "6"}
        return sorted(papers, key=lambda v: cls._component_sort_key(v))

    @classmethod
    def _bestexamhelp_url_for_component(
        cls,
        subject_code: str,
        series: str,
        year: str,
        component: str,
    ) -> str:
        level_slug = SubjectDatabase.get_bestexamhelp_track(subject_code)
        subject_folder = get_subject_folder(subject_code)
        filename = cls._build_filename(subject_code, series, year, "QP", component)
        full_year = cls._coerce_full_year_text(year)
        if not filename or not full_year:
            return ""
        relative = cls._safe_join_path(level_slug, subject_folder, full_year, f"{filename}.pdf")
        return f"{cls.SOURCES['bestexamhelp']['base_url'].rstrip('/')}/{relative}"

    @classmethod
    def _bestexamhelp_component_exists(
        cls,
        subject_code: str,
        series: str,
        year: str,
        component: str,
    ) -> bool:
        target = cls._bestexamhelp_url_for_component(subject_code, series, year, component)
        if not target:
            return False
        cached = cls._url_probe_cache_get(target)
        if cached is not None:
            return bool(cached)

        try:
            resp = cls._http_head(
                target,
                timeout=min(cls.REQUEST_TIMEOUT_SECONDS, cls.COMPONENT_DISCOVERY_TIMEOUT_SECONDS),
                allow_redirects=True,
            )
            try:
                status = int(getattr(resp, "status_code", 0) or 0)
                if status != 200:
                    cls._url_probe_cache_put(target, False, f"head:{status}")
                    return False
                content_type = str(getattr(resp, "headers", {}).get("content-type", "") or "").lower()
                if content_type.startswith("text/html") or content_type.startswith("application/xhtml+xml"):
                    cls._url_probe_cache_put(target, False, "head:html")
                    return False
                cls._url_probe_cache_put(target, True, "head:200")
                return True
            finally:
                cls._safe_close_response(resp)
                maybe_collect_garbage("sources_probe_response_close")
        except Exception:
            cls._url_probe_cache_put(target, False, "head:error")
            return False

    @classmethod
    def _component_label_from_row(cls, subject_code: str, paper: str, year: str) -> str:
        raw_year = cls._coerce_year_int(str(year))
        override = cls.PAPER_NAME_OVERRIDES.get(str(subject_code), {}).get(str(paper), "")
        row = get_subject_row(str(subject_code), str(paper)) or {}
        label = str(row.get("component_label", "") or "").strip()
        if not label:
            alevel_meta = get_alevel_paper(str(subject_code), str(paper)) or {}
            label = str(alevel_meta.get("name", "") or "").strip()

        text = ""
        if label:
            label_norm = re.sub(r"\s+", " ", label).strip()
            if label_norm.lower().startswith(f"paper {paper}"):
                text = label_norm
            else:
                text = f"Paper {paper} ({label_norm})"
        elif override:
            text = f"Paper {paper} ({override})"
        else:
            text = f"Paper {paper}"

        if str(subject_code) == "0580" and raw_year and raw_year < 2025:
            text = f"{text} [OLD SYLLABUS]"
        return text

    @classmethod
    def _component_type_from_row(cls, subject_code: str, paper: str) -> str:
        row = get_subject_row(str(subject_code), str(paper)) or {}
        flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
        assessment = str(flags.get("assessment_type", "")).strip().lower() if isinstance(flags, dict) else ""
        if not assessment:
            alevel_meta = get_alevel_paper(str(subject_code), str(paper)) or {}
            assessment = str(alevel_meta.get("assessment_type", "")).strip().lower()
        if assessment in {"mcq", "listening"}:
            return "MCQ"
        if assessment in {"practical"}:
            return "Practical"
        if assessment in {"coursework"}:
            return "Coursework"
        if assessment in {"speaking"}:
            return "Speaking"
        return "Written"

    @classmethod
    def _component_candidates_for_paper(cls, paper: str) -> List[str]:
        base = str(paper or "").strip()
        out: List[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            text = str(value or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            out.append(text)

        for variant in ("1", "2", "3"):
            _add(f"{base}{variant}")
        _add(base)
        _add(f"0{base}")
        return out

    @classmethod
    def get_available_components(
        cls,
        subject_code: str,
        series: str,
        year: str,
        *,
        refresh: bool = False,
    ) -> List[Dict[str, object]]:
        code = str(subject_code or "").strip()
        session = str(series or "").strip().upper()
        year_text = cls._coerce_full_year_text(year)
        if not (code and session and year_text):
            return []
        if session not in {"MJ", "ON", "FM"}:
            return []
        if not SubjectDatabase.is_searchable_subject(code):
            return []

        cache_key = cls._component_cache_key(code, session, year_text)
        if not refresh:
            cached = cls._component_cache_get(cache_key)
            if cached is not None:
                return cached

        output: List[Dict[str, object]] = []
        for paper in cls._candidate_paper_numbers(code):
            variants: List[str] = []
            for component in cls._component_candidates_for_paper(paper):
                if cls._bestexamhelp_component_exists(code, session, year_text, component):
                    variants.append(str(component))

            normalized_variants: List[str] = []
            seen_variants: set[str] = set()
            for variant in sorted(variants, key=lambda value: cls._component_sort_key(value)):
                text = str(variant).strip()
                if not text or text in seen_variants:
                    continue
                seen_variants.add(text)
                normalized_variants.append(text)
            if not normalized_variants:
                continue

            preferred_variant = f"{paper}1"
            full_component = preferred_variant if preferred_variant in normalized_variants else normalized_variants[0]
            output.append(
                {
                    "component": str(paper),
                    "full_component": str(full_component),
                    "name": cls._component_label_from_row(code, paper, year_text),
                    "variants": normalized_variants,
                    "type": cls._component_type_from_row(code, paper),
                }
            )

        output.sort(key=lambda row: cls._component_sort_key(row.get("component", "")))
        cls._component_cache_put(cache_key, output)
        return output

    @staticmethod
    def _component_paper_number(component: str) -> str:
        text = str(component or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return ""
        return digits[0]

    @classmethod
    def _apply_locked_variant_to_components(cls, components: List[str], variant: Optional[str]) -> List[str]:
        token = str(variant or "").strip()
        if token not in {"1", "2", "3"}:
            return [str(c).strip() for c in components if str(c).strip()]
        updated: List[str] = []
        seen: set[str] = set()
        for component in components:
            text = str(component or "").strip()
            if not text:
                continue
            paper = cls._component_paper_number(text)
            if paper:
                text = f"{paper}{token}"
            if text in seen:
                continue
            seen.add(text)
            updated.append(text)
        return updated

    @staticmethod
    def _is_transient_source_error(exc: BaseException) -> bool:
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        if isinstance(exc, requests.RequestException):
            return True
        if isinstance(exc, TimeoutError):
            return True
        return False

    @classmethod
    def _search_from_source_with_retry(
        cls,
        source_name: str,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[Dict]:
        if cls._source_is_cooling_down(source_name):
            cls._log_event(
                "source.cooldown_skip",
                source=source_name,
                subject=subject_code,
                series=series,
                year=year,
                component=component,
            )
            return []

        attempts = max(1, int(cls.SOURCE_SEARCH_RETRY_COUNT))
        last_exc: Optional[BaseException] = None
        for attempt in range(attempts):
            if cancel_check is not None:
                try:
                    if bool(cancel_check()):
                        return []
                except Exception:
                    pass
            try:
                rows = cls._search_from_source(
                    source_name,
                    subject_code,
                    year,
                    series,
                    component,
                    doc_types,
                )
                cls._record_source_success(source_name)
                return rows
            except Exception as exc:  # pragma: no cover - network/transient paths
                last_exc = exc
                is_transient = cls._is_transient_source_error(exc)
                cls._record_source_failure(source_name, transient=is_transient)
                if attempt >= (attempts - 1) or (not is_transient):
                    raise
                time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
        return []

    @classmethod
    def _parallel_search_remaining_sources(
        cls,
        source_order: List[str],
        subject_code: str,
        year_text: str,
        series: str,
        component_text: str,
        doc_types: List[str],
        requested_types: List[str],
        collected_by_type: Dict[str, Dict[str, object]],
        used_sources: List[str],
        query_id: str = "",
        deadline_ts: Optional[float] = None,
        progress_callback: Optional[Callable[[str, Dict[str, object]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        if not source_order:
            return

        max_workers = max(1, min(int(cls.SOURCE_SEARCH_MAX_WORKERS), len(source_order)))
        futures = {}
        source_rows: Dict[str, List[Dict]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for source_name in source_order:
                futures[
                    executor.submit(
                        cls._search_from_source_with_retry,
                        source_name,
                        subject_code,
                        year_text,
                        series,
                        component_text,
                        doc_types,
                        cancel_check,
                    )
                ] = source_name

            pending = set(futures.keys())
            while pending:
                if deadline_ts is not None and time.monotonic() >= float(deadline_ts):
                    break
                if cancel_check is not None:
                    try:
                        if bool(cancel_check()):
                            break
                    except Exception:
                        pass
                timeout = 0.15
                if deadline_ts is not None:
                    timeout = max(0.01, min(timeout, float(deadline_ts) - time.monotonic()))
                done, pending = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    source_name = futures.get(future, "")
                    started = time.perf_counter()
                    try:
                        source_results = list(future.result() or [])
                    except Exception as exc:
                        cls._log_event(
                            "source.error",
                            query_id=query_id,
                            source=source_name,
                            subject=subject_code,
                            series=series,
                            year=year_text,
                            component=component_text,
                            error=str(exc),
                        )
                        source_results = []
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    source_rows[source_name] = source_results
                    found_types = sorted({cls._result_doc_type(row) for row in source_results})
                    cls._log_event(
                        "source.result",
                        query_id=query_id,
                        source=source_name,
                        subject=subject_code,
                        series=series,
                        year=year_text,
                        component=component_text,
                        elapsed_ms=round(elapsed_ms, 2),
                        count=len(source_results),
                        types=found_types,
                        mode="parallel",
                    )
                    cls._debug_log(
                        "[sources] "
                        f"{source_name} {subject_code} {series}{year_text} c{component_text} "
                        f"-> {len(source_results)} docs {found_types} in {elapsed_ms:.0f} ms (parallel)"
                    )

                    if progress_callback is not None:
                        try:
                            progress_callback(
                                f"Tried {source_name} ({len(source_results)} docs)",
                                {
                                    "query_id": query_id,
                                    "source": source_name,
                                    "count": len(source_results),
                                    "year": year_text,
                                    "series": series,
                                    "component": component_text,
                                },
                            )
                        except Exception:
                            pass

        for future in futures:
            if not future.done():
                future.cancel()

        # Deterministic merge by configured source order, not completion race.
        for source_name in source_order:
            source_results = list(source_rows.get(source_name, []) or [])
            if not source_results:
                continue
            used_sources.append(source_name)
            for item in source_results:
                item_type = cls._result_doc_type(item)
                if requested_types and item_type not in requested_types:
                    continue
                if item_type in collected_by_type:
                    continue
                collected_by_type[item_type] = dict(item)
            if requested_types and all(token in collected_by_type for token in requested_types):
                break

    @classmethod
    def search_papers_multi_source(
        cls,
        subject_code: str,
        series_list: List[str],
        components: List[str],
        years: List[str],
        doc_types: List[str],
        include_specimen: bool = False,
        fm_locked_variant: Optional[str] = None,
        series_component_map: Optional[Dict[str, List[str]]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[str, Dict[str, object]], None]] = None,
        partial_callback: Optional[Callable[[List[PaperGroup], bool], None]] = None,
        _allow_math_fallback: bool = True,
    ) -> List[PaperGroup]:
        """Try sources in priority order until papers found, then return grouped resources."""
        cls._ensure_search_logger(force=True)
        subject_text = str(subject_code or "").strip()
        if not SubjectDatabase.is_searchable_subject(subject_text):
            cls._log_event(
                "search.blocked_subject",
                subject=subject_text,
                reason="removed_subject_code",
            )
            return []
        runtime_cfg = cls._search_runtime_config()
        fast_first_target_ms = int(runtime_cfg.get("fast_first_target_ms", 2500) or 2500)
        max_total_ms = int(runtime_cfg.get("max_total_ms", 10000) or 10000)
        enable_background_enrichment = bool(runtime_cfg.get("enable_background_enrichment", True))
        stop_on_first_source_hit = bool(runtime_cfg.get("stop_on_first_source_hit", True))

        default_order = sorted(cls.SOURCES.keys(), key=lambda k: cls.SOURCES[k]["priority"])
        preferred = SubjectDatabase.SUBJECT_SOURCE_MAP.get(subject_code, default_order)
        source_order = [s for s in preferred if s in cls.SOURCES] or default_order
        source_order = cls._runtime_source_order(subject_code, source_order)

        # Specimen mode is temporarily disabled in Alpha 6.3.
        include_specimen = False

        groups_by_key: Dict[Tuple[str, str, str, str], PaperGroup] = {}
        default_components = cls._clean_component_list(components)
        normalized_series_component_map: Dict[str, List[str]] = {}
        if series_component_map:
            for series_code, mapped_components in series_component_map.items():
                code = str(series_code or "").strip().upper()
                if not code:
                    continue
                cleaned = cls._clean_component_list(mapped_components)
                if cleaned:
                    normalized_series_component_map[code] = cleaned

        def _is_cancelled() -> bool:
            if cancel_check is None:
                return False
            try:
                return bool(cancel_check())
            except Exception:
                return False

        level = SubjectDatabase.get_exam_level(subject_code)
        search_query = SearchQuery(
            subject_code=str(subject_code or "").strip(),
            level=str(level or "").strip(),
            series_list=list(series_list or []),
            components=list(components or []),
            years=list(years or []),
            doc_types=list(doc_types or []),
        )
        query_id = search_query.fingerprint()
        started_monotonic = time.monotonic()
        fast_deadline = started_monotonic + (max(500, fast_first_target_ms) / 1000.0)
        max_deadline = started_monotonic + (max(max_total_ms, fast_first_target_ms) / 1000.0)

        def _emit_progress(message: str, **metrics: object) -> None:
            payload = dict(metrics)
            payload.setdefault("query_id", query_id)
            if progress_callback is not None:
                try:
                    progress_callback(str(message or ""), payload)
                except Exception:
                    pass
            cls._log_event("progress_update", query_id=query_id, message=str(message or ""), metrics=payload)

        def _sort_key(group: PaperGroup) -> Tuple[str, int, int, str, str]:
            year_num = cls._coerce_year_int(group.year)
            session_order = {"MJ": 0, "ON": 1, "FM": 2, "SP": 3}.get(str(group.session).upper(), 9)
            return (
                str(group.subject_name),
                year_num,
                session_order,
                str(group.component),
                str(group.source),
            )

        last_partial_signature = ""

        def _emit_partial() -> None:
            nonlocal last_partial_signature
            if partial_callback is None:
                return
            snapshot = sorted(list(groups_by_key.values()), key=_sort_key)
            signature = "|".join(
                f"{group.subject_code}:{group.session}:{group.year}:{group.component}:{len(group.primary_docs)}:{len(group.resources)}"
                for group in snapshot
            )
            if signature == last_partial_signature:
                return
            last_partial_signature = signature
            try:
                partial_callback(snapshot, False)
            except Exception:
                pass

        cancelled = False
        requested_types = cls._normalize_requested_doc_types(doc_types)
        effective_doc_types = list(requested_types or doc_types or [])
        search_series = [
            str(s).strip().upper()
            for s in series_list
            if str(s).strip() and str(s).strip().upper() != "SP"
        ]

        fm_variant = str(fm_locked_variant or "").strip()
        if "FM" in search_series:
            fm_components = normalized_series_component_map.get("FM", default_components)
            fm_papers = [
                paper
                for paper in (cls._component_paper_number(component) for component in fm_components)
                if paper
            ]
            if fm_variant not in {"1", "2", "3"} and fm_papers:
                fm_cache_key = cls._fm_variant_cache_key(subject_code, fm_papers, years)
                cached_variant = cls._fm_variant_cache_get(fm_cache_key)
                if cached_variant in {"1", "2", "3"}:
                    fm_variant = cached_variant
                elif not _is_cancelled():
                    detected = cls.detect_fm_locked_variant(
                        subject_code=subject_code,
                        paper_numbers=fm_papers,
                        years=years,
                        doc_types=doc_types,
                    )
                    fm_variant = detected if detected in {"1", "2", "3"} else "2"
                    cls._fm_variant_cache_put(fm_cache_key, fm_variant)
            if fm_variant not in {"1", "2", "3"}:
                fm_variant = "2"
            if "FM" in normalized_series_component_map:
                normalized_series_component_map["FM"] = cls._apply_locked_variant_to_components(
                    normalized_series_component_map["FM"],
                    fm_variant,
                )

        cache_key = cls._search_cache_key_for_query(
            search_query,
            fm_locked_variant=fm_variant,
            series_component_map=normalized_series_component_map,
        )
        cls._log_event(
            "search.start",
            query_id=query_id,
            subject=subject_code,
            level=level,
            series=search_series,
            components=default_components,
            years=years,
            doc_types=requested_types,
            source_order=source_order,
            fast_first_target_ms=fast_first_target_ms,
            max_total_ms=max_total_ms,
            stop_on_first_source_hit=stop_on_first_source_hit,
        )
        _emit_progress("Checking cache...", stage="cache_check")
        cached_result = cls._search_cache_get_for_query(
            search_query,
            fm_locked_variant=fm_variant,
            series_component_map=normalized_series_component_map,
        )
        if cached_result is not None:
            cached_groups = list(cached_result.groups)
            cls._log_event(
                "search.complete",
                query_id=query_id,
                from_cache=True,
                groups=len(cached_groups),
                elapsed_ms=round((time.monotonic() - started_monotonic) * 1000.0, 2),
            )
            return cached_groups

        is_owner, joined_groups = cls._join_or_acquire_active_query(
            cache_key,
            wait_seconds=(max_total_ms / 1000.0) + 0.75,
        )
        if not is_owner:
            if joined_groups is not None:
                cls._log_event(
                    "search.complete",
                    query_id=query_id,
                    from_inflight=True,
                    groups=len(joined_groups),
                    elapsed_ms=round((time.monotonic() - started_monotonic) * 1000.0, 2),
                )
                return joined_groups
            cached_retry = cls._search_cache_get(cache_key)
            if cached_retry is not None:
                return cached_retry
            return []

        final_groups: List[PaperGroup] = []
        seen_success_sources: set[str] = set()
        result_status = "error"
        for series in search_series:
            if _is_cancelled():
                cancelled = True
                break
            if time.monotonic() >= max_deadline:
                break
            series_components = normalized_series_component_map.get(series, default_components)
            if series == "FM":
                series_components = cls._apply_locked_variant_to_components(series_components, fm_variant)
            if not series_components:
                continue
            for component_text in series_components:
                if _is_cancelled():
                    cancelled = True
                    break
                if time.monotonic() >= max_deadline:
                    break
                for year in years:
                    if _is_cancelled():
                        cancelled = True
                        break
                    if time.monotonic() >= max_deadline:
                        break
                    year_text = str(year).strip()
                    collected_by_type: Dict[str, Dict[str, object]] = {}
                    used_sources: List[str] = []
                    if source_order:
                        source_name = source_order[0]
                        if _is_cancelled():
                            cancelled = True
                            break
                        started = time.perf_counter()
                        _emit_progress(
                            f"Querying {source_name} ({level} {subject_code})...",
                            source=source_name,
                            series=series,
                            year=year_text,
                            component=component_text,
                        )
                        cls._log_event(
                            "source.try",
                            query_id=query_id,
                            source=source_name,
                            subject=subject_code,
                            series=series,
                            year=year_text,
                            component=component_text,
                            mode="primary",
                        )
                        try:
                            source_results = cls._search_from_source_with_retry(
                                source_name=source_name,
                                subject_code=subject_code,
                                year=year_text,
                                series=series,
                                component=component_text,
                                doc_types=effective_doc_types,
                                cancel_check=_is_cancelled,
                            )
                        except Exception as exc:
                            cls._log_event(
                                "source.error",
                                query_id=query_id,
                                source=source_name,
                                subject=subject_code,
                                series=series,
                                year=year_text,
                                component=component_text,
                                error=str(exc),
                                mode="primary",
                            )
                            source_results = []
                        elapsed_ms = (time.perf_counter() - started) * 1000.0
                        if source_results:
                            used_sources.append(source_name)
                            seen_success_sources.add(source_name)
                        found_types = sorted({cls._result_doc_type(row) for row in source_results})
                        cls._log_event(
                            "source.result",
                            query_id=query_id,
                            source=source_name,
                            subject=subject_code,
                            series=series,
                            year=year_text,
                            component=component_text,
                            elapsed_ms=round(elapsed_ms, 2),
                            count=len(source_results),
                            types=found_types,
                            mode="primary",
                        )
                        cls._debug_log(
                            "[sources] "
                            f"{source_name} {subject_code} {series}{year_text} c{component_text} "
                            f"-> {len(source_results)} docs {found_types} in {elapsed_ms:.0f} ms"
                        )
                        for item in source_results:
                            item_type = cls._result_doc_type(item)
                            if requested_types and item_type not in requested_types:
                                continue
                            if item_type in collected_by_type:
                                continue
                            collected_by_type[item_type] = dict(item)

                        if stop_on_first_source_hit and collected_by_type:
                            cls._log_event(
                                "search.early_stop",
                                query_id=query_id,
                                source=source_name,
                                subject=subject_code,
                                series=series,
                                year=year_text,
                                component=component_text,
                                elapsed_ms=round((time.monotonic() - started_monotonic) * 1000.0, 2),
                                reason="primary_source_hit",
                            )
                            needs_more = False
                        else:
                            needs_more = not (
                                requested_types and all(token in collected_by_type for token in requested_types)
                            )
                        if needs_more and len(source_order) > 1 and not _is_cancelled():
                            stage_a_sources = source_order[1:2]
                            if stage_a_sources:
                                _emit_progress(
                                    f"Falling back to {stage_a_sources[0]}...",
                                    source=stage_a_sources[0],
                                    stage="fast-first",
                                )
                                cls._parallel_search_remaining_sources(
                                    source_order=stage_a_sources,
                                    subject_code=subject_code,
                                    year_text=year_text,
                                    series=series,
                                    component_text=component_text,
                                    doc_types=effective_doc_types,
                                    requested_types=requested_types,
                                    collected_by_type=collected_by_type,
                                    used_sources=used_sources,
                                    query_id=query_id,
                                    deadline_ts=fast_deadline,
                                    progress_callback=lambda msg, met: _emit_progress(msg, **dict(met or {})),
                                    cancel_check=_is_cancelled,
                                )
                                for source in used_sources:
                                    seen_success_sources.add(source)
                                if stop_on_first_source_hit and collected_by_type:
                                    cls._log_event(
                                        "search.early_stop",
                                        query_id=query_id,
                                        source=used_sources[0] if used_sources else stage_a_sources[0],
                                        subject=subject_code,
                                        series=series,
                                        year=year_text,
                                        component=component_text,
                                        elapsed_ms=round((time.monotonic() - started_monotonic) * 1000.0, 2),
                                        reason="fallback_source_hit",
                                    )
                                    needs_more = False

                        if not (stop_on_first_source_hit and collected_by_type):
                            needs_more = not (
                                requested_types and all(token in collected_by_type for token in requested_types)
                            )
                        if (
                            needs_more
                            and enable_background_enrichment
                            and len(source_order) > 2
                            and not _is_cancelled()
                            and time.monotonic() < max_deadline
                        ):
                            _emit_progress(
                                "Enriching missing documents...",
                                stage="background",
                            )
                            cls._parallel_search_remaining_sources(
                                source_order=source_order[2:],
                                subject_code=subject_code,
                                year_text=year_text,
                                series=series,
                                component_text=component_text,
                                doc_types=effective_doc_types,
                                requested_types=requested_types,
                                collected_by_type=collected_by_type,
                                used_sources=used_sources,
                                query_id=query_id,
                                deadline_ts=max_deadline,
                                progress_callback=lambda msg, met: _emit_progress(msg, **dict(met or {})),
                                cancel_check=_is_cancelled,
                            )
                            for source in used_sources:
                                seen_success_sources.add(source)

                    if _is_cancelled():
                        cancelled = True
                        break
                    if cancelled:
                        break
                    if not collected_by_type:
                        continue
                    preferred_source = used_sources[0] if used_sources else ""
                    for item in collected_by_type.values():
                        row = dict(item)
                        if preferred_source:
                            row.setdefault("origin_source", str(row.get("source", "")).strip())
                            row["source"] = preferred_source
                        cls._add_result_to_groups(
                            groups_by_key,
                            row,
                            fm_variant if series == "FM" else None,
                        )
                    _emit_partial()
                if cancelled:
                    break
            if cancelled:
                break

        if include_specimen and not cancelled:
            specimen_items = cls._search_specimen_multi_source(
                subject_code,
                components,
                effective_doc_types,
                source_order,
            )
            for item in specimen_items:
                cls._add_result_to_groups(groups_by_key, item, None)

        groups = list(groups_by_key.values())
        cls._attach_compound_resources(groups)
        sorted_groups = sorted(groups, key=_sort_key)

        if (
            not sorted_groups
            and not cancelled
            and _allow_math_fallback
            and str(subject_code) in {"0580", "0607"}
            and not _is_cancelled()
        ):
            fallback_code = "0607" if str(subject_code) == "0580" else "0580"
            _emit_progress(
                f"No direct match found. Retrying via mapped subject {fallback_code}...",
                fallback_subject=fallback_code,
            )
            fallback_groups = cls.search_papers_multi_source(
                subject_code=fallback_code,
                series_list=series_list,
                components=components,
                years=years,
                doc_types=doc_types,
                include_specimen=include_specimen,
                fm_locked_variant=fm_locked_variant,
                series_component_map=series_component_map,
                cancel_check=cancel_check,
                progress_callback=progress_callback,
                partial_callback=None,
                _allow_math_fallback=False,
            )
            merged: Dict[Tuple[str, str, str, str], PaperGroup] = {}
            for group in list(sorted_groups) + list(fallback_groups):
                key = (
                    str(group.subject_code),
                    str(group.session),
                    str(group.year),
                    str(group.component),
                )
                if key not in merged:
                    merged[key] = group
            sorted_groups = sorted(list(merged.values()), key=_sort_key)

        final_groups = list(sorted_groups)
        if final_groups:
            if not seen_success_sources:
                seen_success_sources = {str(group.source or "") for group in final_groups if str(group.source or "")}
            SubjectDatabase.record_subject_availability(
                subject_code,
                sources=sorted(seen_success_sources),
                verified=True,
                checked_at=time.time(),
            )
        else:
            SubjectDatabase.record_subject_availability(
                subject_code,
                sources=source_order,
                verified=False,
                checked_at=time.time(),
            )

        if not cancelled:
            result_status = "success" if final_groups else "empty"
            result = SearchResult(
                groups=final_groups,
                status=result_status,
                from_cache=False,
                cancelled=False,
            )
            cls._search_cache_put_for_query(
                search_query,
                fm_locked_variant=fm_variant,
                series_component_map=normalized_series_component_map,
                result=result,
            )
        else:
            result_status = "error"

        if partial_callback is not None:
            try:
                partial_callback(final_groups, True)
            except Exception:
                pass

        cls._log_event(
            "search.complete",
            query_id=query_id,
            status=result_status,
            cancelled=cancelled,
            groups=len(final_groups),
            elapsed_ms=round((time.monotonic() - started_monotonic) * 1000.0, 2),
        )
        cls._complete_active_query(cache_key, final_groups)
        if not final_groups and not cancelled:
            raise PaperNotFoundError("Paper not found on any configured source.")
        return final_groups

    @staticmethod
    def _clean_component_list(components: Optional[List[str]]) -> List[str]:
        cleaned: List[str] = []
        seen: set[str] = set()
        for component in components or []:
            text = str(component or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    @classmethod
    def detect_fm_locked_variant(
        cls,
        subject_code: str,
        paper_numbers: List[str],
        years: List[str],
        doc_types: List[str],
    ) -> str:
        """Auto-detect the most likely FM variant (second component digit)."""
        papers = [p for p in {str(x).strip() for x in paper_numbers} if p and p[0].isdigit()]
        if not papers:
            return "2"

        probe_years = [str(y).strip() for y in years if str(y).strip()]
        if not probe_years:
            probe_years = [str(datetime.now().year % 100)]

        variant_cache_key = cls._fm_variant_cache_key(subject_code, papers, probe_years)
        cached_variant = cls._fm_variant_cache_get(variant_cache_key)
        if cached_variant in {"1", "2", "3"}:
            return cached_variant

        probe_types = [dt for dt in doc_types if str(dt).upper() in {"QP", "P", "MS", "GT"}]
        if not probe_types:
            probe_types = ["QP"]

        default_order = sorted(cls.SOURCES.keys(), key=lambda k: cls.SOURCES[k]["priority"])
        preferred = SubjectDatabase.SUBJECT_SOURCE_MAP.get(subject_code, default_order)
        source_order = [s for s in preferred if s in cls.SOURCES] or default_order
        source_order = cls._runtime_source_order(subject_code, source_order)

        variant_scores: Dict[str, Dict[str, int]] = {
            "1": {"qp": 0, "all": 0},
            "2": {"qp": 0, "all": 0},
            "3": {"qp": 0, "all": 0},
        }

        for variant in ["1", "2", "3"]:
            variant_components = [f"{paper[0]}{variant}" for paper in papers]
            for year in probe_years:
                for component in variant_components:
                    for source_name in source_order:
                        try:
                            source_results = cls._search_from_source_with_retry(
                                source_name=source_name,
                                subject_code=subject_code,
                                year=year,
                                series="FM",
                                component=component,
                                doc_types=probe_types,
                            )
                        except Exception:
                            source_results = []
                        if source_results:
                            variant_scores[variant]["all"] += len(source_results)
                            if any(str(row.get("type", "")).upper() in {"QP", "P"} for row in source_results):
                                variant_scores[variant]["qp"] += 1
                            break

        tie_order = {"2": 0, "1": 1, "3": 2}
        ranked = sorted(
            ["1", "2", "3"],
            key=lambda v: (
                -variant_scores[v]["qp"],
                -variant_scores[v]["all"],
                tie_order[v],
            ),
        )

        best = ranked[0] if ranked else "2"
        if variant_scores.get(best, {}).get("qp", 0) == 0 and variant_scores.get(best, {}).get("all", 0) == 0:
            cls._fm_variant_cache_put(variant_cache_key, "2")
            return "2"
        cls._fm_variant_cache_put(variant_cache_key, best)
        return best

    @classmethod
    def _add_result_to_groups(
        cls,
        groups_by_key: Dict[Tuple[str, str, str, str], PaperGroup],
        item: Dict,
        locked_variant: Optional[str],
    ) -> None:
        kind = cls._kind_from_item(item)
        if kind == "ER":
            return
        session = str(item.get("series", "")).strip().upper()
        key = (
            str(item.get("subject_code", "")).strip(),
            session,
            str(item.get("year", "")).strip(),
            str(item.get("component", "")).strip(),
        )
        group = groups_by_key.get(key)
        if group is None:
            group = PaperGroup(
                subject_code=key[0],
                subject_name=str(item.get("subject") or SubjectDatabase.get_subject_name(key[0])),
                session=session,
                year=key[2],
                component=key[3],
                source=str(item.get("source", "")).strip(),
                locked_variant=locked_variant if session == "FM" else None,
                is_specimen=bool(item.get("is_specimen", False) or session == "SP"),
            )
            groups_by_key[key] = group
        resource = PaperResource(
            kind=kind,
            filename=str(item.get("filename", "")).strip(),
            url=str(item.get("url", "")).strip(),
            source=str(item.get("source", "")).strip(),
            downloaded=bool(item.get("downloaded", False)),
            direct_url=str(item.get("direct_url", item.get("url", ""))).strip(),
            viewer_url=str(item.get("viewer_url", "")).strip(),
            open_url=str(item.get("open_url", item.get("url", ""))).strip(),
            download_url=str(item.get("download_url", item.get("url", ""))).strip(),
            resource_family=str(item.get("resource_family", "")).strip(),
            resource_token=str(item.get("resource_token", "")).strip(),
            extension=str(item.get("extension", "")).strip(),
        )

        if kind in {"IN", "SF", "AU", "TN", "MAP"}:
            if kind not in group.resources:
                group.resources[kind] = resource
        else:
            if kind not in group.primary_docs:
                group.primary_docs[kind] = resource

    @staticmethod
    def _coerce_year_int(text: str) -> int:
        raw = str(text or "").strip()
        if not raw:
            return 0
        m4 = re.search(r"(20\d{2})", raw)
        if m4:
            return int(m4.group(1))
        m2 = re.search(r"(?<!\d)(\d{2})(?!\d)", raw)
        if m2:
            return 2000 + int(m2.group(1))
        return 0

    @staticmethod
    def _kind_from_item(item: Dict) -> str:
        item_type = str(item.get("type", "")).strip().upper()
        if item_type in {"P", "QP"}:
            return "SP_QP" if item.get("is_specimen") else "QP"
        if item_type == "MS":
            return "SP_MS" if item.get("is_specimen") else "MS"
        if item_type == "GT":
            return "GT"
        if item_type == "ER":
            return "ER"
        if item_type == "IN":
            return "IN"
        if item_type == "SF":
            return "SF"
        if item_type in {"AU", "AUDIO"}:
            return "AU"
        if item_type in {"TN", "TRANSCRIPT"}:
            return "TN"
        if item_type == "MAP":
            return "MAP"
        return item_type or "QP"

    @classmethod
    def _search_from_source(
        cls,
        source_name: str,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        provider = cls._get_source_provider(source_name)
        if provider is None:
            return []
        return provider.search(
            manager=cls,
            subject_code=subject_code,
            year=year,
            series=series,
            component=component,
            doc_types=doc_types,
        )

    @classmethod
    def _build_filename(
        cls,
        subject_code: str,
        series: str,
        year: str,
        doc_type: str,
        component: str,
    ) -> str:
        year_short = str(year)[-2:]
        series_code = series_to_code(series)

        if doc_type == "GT":
            return f"{subject_code}_{series_code}{year_short}_gt"

        file_type = {"QP": "qp", "P": "qp", "MS": "ms", "GT": "gt", "ER": "er"}.get(doc_type, "qp")
        return f"{subject_code}_{series_code}{year_short}_{file_type}_{component}"

    @classmethod
    def _build_papacambridge_direct_url(
        cls,
        subject_code: str,
        year: str,
        series: str,
        doc_type: str,
        component: str,
    ) -> str:
        filename = cls._build_filename(subject_code, series, year, doc_type, component)
        base_url = cls._pastpapersco_upload_bases()[0]
        return f"{base_url}/{filename}.pdf"

    @classmethod
    def _pastpapersco_upload_bases(cls) -> List[str]:
        configured = cls.SOURCES.get("pastpapersco", {}) or {}
        raw_bases = list(configured.get("upload_bases", []) or [])
        base_url = str(configured.get("base_url", "") or "").strip()
        if base_url:
            raw_bases.insert(0, base_url)

        out: List[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            url = str(value or "").strip().rstrip("/")
            if not url or url in seen:
                return
            seen.add(url)
            out.append(url)

        preferred = str(cls._pastpapersco_preferred_base or "").strip().rstrip("/")
        if preferred:
            _add(preferred)
        for candidate in raw_bases:
            _add(str(candidate))
        return out or [cls.PASTPAPERSCO_CANONICAL_UPLOAD_BASE]

    @classmethod
    def _papacambridge_head_probe(cls, url: str) -> Tuple[bool, int, str, str]:
        target = str(url or "").strip()
        if not target:
            return (False, 0, "", "")
        try:
            response = cls._http_head(
                target,
                timeout=cls.PAPACAMBRIDGE_HEAD_TIMEOUT_SECONDS,
                allow_redirects=True,
                headers={"User-Agent": cls.REQUEST_HEADERS.get("User-Agent", "")},
            )
            try:
                status = int(getattr(response, "status_code", 0) or 0)
                final_url = str(getattr(response, "url", "") or "").strip()
                content_type = str(getattr(response, "headers", {}).get("content-type", "") or "").strip().lower()
            except Exception:
                status = 0
                final_url = ""
                content_type = ""
            finally:
                cls._safe_close_response(response)
        except Exception:
            return (False, 0, "", "")
        ok = 200 <= status < 300
        if ok and not cls._papacambridge_response_looks_like_asset(
            requested_url=target,
            final_url=final_url,
            content_type=content_type,
        ):
            ok = False
        return (ok, status, final_url, content_type)

    @classmethod
    def _pastpapersco_asset_probe(cls, url: str) -> Tuple[bool, int]:
        target = str(url or "").strip()
        if not target:
            return (False, 0)

        cached = cls._url_probe_cache_get(target)
        if cached is not None:
            return (bool(cached), 200 if bool(cached) else 404)

        owner, inflight_event = cls._acquire_url_probe_slot(target)
        if not owner and inflight_event is not None:
            inflight_event.wait(timeout=max(0.2, cls.URL_PROBE_REQUEST_TIMEOUT_SECONDS + 0.5))
            cached_after_wait = cls._url_probe_cache_get(target)
            if cached_after_wait is not None:
                return (bool(cached_after_wait), 200 if bool(cached_after_wait) else 404)
            return (False, 0)

        try:
            head_ok, status, _final_url, content_type = cls._papacambridge_head_probe(target)
            if head_ok:
                cls._url_probe_cache_put(target, True, "head:ok")
                return (True, status)
            # If the host is unreachable, avoid doubling latency with an extra GET.
            if status == 0:
                return (False, 0)
            if status in {403, 404}:
                cls._url_probe_cache_put(target, False, f"head:{status}")
                return (False, status)

            content_type_norm = str(content_type or "").strip().lower()
            if 200 <= status < 300 and (
                content_type_norm.startswith("text/html")
                or content_type_norm.startswith("application/xhtml+xml")
                or content_type_norm.startswith("text/plain")
            ):
                cls._url_probe_cache_put(target, False, "head:not_asset")
                return (False, status)

            # PastPapers can return 200 HTML wrappers for missing assets.
            # Confirm with a tiny ranged GET so we only accept real PDFs.
            try:
                resp = cls._http_get(
                    target,
                    timeout=max(1.0, cls.PAPACAMBRIDGE_HEAD_TIMEOUT_SECONDS + 0.25),
                    allow_redirects=True,
                    stream=True,
                    headers={
                        "Range": "bytes=0-4095",
                        "Accept": "application/pdf,*/*;q=0.8",
                        "Referer": "https://pastpapers.co/",
                    },
                )
                try:
                    try:
                        get_status = int(getattr(resp, "status_code", 0) or 0)
                    except Exception:
                        get_status = 0

                    if get_status not in {200, 206}:
                        cls._url_probe_cache_put(target, False, f"get:{get_status or status}")
                        return (False, get_status or status)

                    final_url = str(getattr(resp, "url", "") or "").strip().lower()
                    content_type = str(getattr(resp, "headers", {}).get("content-type", "") or "").strip().lower()
                    if content_type.startswith("text/html") or content_type.startswith("application/xhtml+xml"):
                        cls._url_probe_cache_put(target, False, "get:html")
                        return (False, get_status)

                    first_chunk = b""
                    try:
                        for chunk in resp.iter_content(chunk_size=4096):
                            if chunk:
                                first_chunk = bytes(chunk[:4096])
                                break
                    except Exception:
                        first_chunk = b""

                    sample = first_chunk.lstrip().lower()
                    if sample.startswith(b"%pdf-"):
                        cls._url_probe_cache_put(target, True, "get:pdf_signature")
                        return (True, get_status)
                    if sample.startswith(b"<!doctype html") or sample.startswith(b"<html"):
                        cls._url_probe_cache_put(target, False, "get:html_signature")
                        return (False, get_status)
                    if "application/pdf" in content_type and final_url.endswith(".pdf"):
                        cls._url_probe_cache_put(target, True, "get:pdf_content_type")
                        return (True, get_status)

                    cls._url_probe_cache_put(target, False, "get:unknown")
                    return (False, get_status)
                finally:
                    cls._safe_close_response(resp)
                    maybe_collect_garbage("sources_url_exists_response_close")
            except Exception:
                cls._url_probe_cache_put(target, False, "get:error")
                return (False, status)
        finally:
            cls._release_url_probe_slot(target)

    @staticmethod
    def _papacambridge_response_looks_like_asset(
        requested_url: str,
        final_url: str,
        content_type: str,
    ) -> bool:
        req_path = str(urlsplit(str(requested_url or "")).path or "").lower()
        final_path = str(urlsplit(str(final_url or "")).path or "").lower()
        req_ext = os.path.splitext(req_path)[1].lower()
        final_ext = os.path.splitext(final_path)[1].lower()
        ctype = str(content_type or "").lower()

        if ctype.startswith("text/html") or ctype.startswith("application/xhtml+xml"):
            return False
        if ctype.startswith("text/plain"):
            return False

        if req_ext:
            if final_ext and final_ext != req_ext:
                return False
            if final_path and not final_path.endswith(req_ext):
                return False

        return True

    @classmethod
    def _url_exists(cls, url: str) -> bool:
        target = str(url or "").strip()
        if not target:
            return False
        cached = cls._url_probe_cache_get(target)
        if cached is not None:
            return bool(cached)

        owner, inflight_event = cls._acquire_url_probe_slot(target)
        if not owner and inflight_event is not None:
            inflight_event.wait(timeout=max(0.2, cls.URL_PROBE_REQUEST_TIMEOUT_SECONDS + 0.5))
            cached_after_wait = cls._url_probe_cache_get(target)
            return bool(cached_after_wait) if cached_after_wait is not None else False

        def _cache(value: bool, source_status: str = "probe") -> bool:
            cls._url_probe_cache_put(target, bool(value), source_status)
            return bool(value)

        def _looks_like_pdf_bytes(payload: bytes) -> bool:
            sample = bytes(payload or b"").lstrip()
            return sample.startswith(b"%PDF-")

        def _looks_like_html_bytes(payload: bytes) -> bool:
            sample = bytes(payload or b"").lstrip().lower()
            return (
                sample.startswith(b"<!doctype html")
                or sample.startswith(b"<html")
                or sample.startswith(b"<?xml")
            )

        def _content_type_indicates_pdf(content_type: str) -> bool:
            ctype = str(content_type or "").strip().lower()
            return "application/pdf" in ctype

        def _content_type_indicates_html(content_type: str) -> bool:
            ctype = str(content_type or "").strip().lower()
            return (
                ctype.startswith("text/html")
                or ctype.startswith("text/plain")
                or ctype.startswith("application/xhtml+xml")
            )

        try:
            # Fast HEAD probe first.
            try:
                head = cls._http_head(
                    target,
                    timeout=min(cls.REQUEST_TIMEOUT_SECONDS, cls.URL_PROBE_REQUEST_TIMEOUT_SECONDS),
                    allow_redirects=True,
                )
                try:
                    status = int(getattr(head, "status_code", 0) or 0)
                    if status == 200:
                        head_type = head.headers.get("content-type", "")
                        if _content_type_indicates_pdf(head_type):
                            return _cache(True, "head:pdf")
                        if _content_type_indicates_html(head_type):
                            return _cache(False, "head:html")
                    elif status in {403, 404}:
                        return _cache(False, f"head:{status}")
                finally:
                    cls._safe_close_response(head)
            except Exception:
                pass

            # Fallback: lightweight GET and inspect first chunk/signature.
            try:
                resp = cls._http_get(
                    target,
                    timeout=min(cls.REQUEST_TIMEOUT_SECONDS, cls.URL_PROBE_REQUEST_TIMEOUT_SECONDS),
                    allow_redirects=True,
                    stream=True,
                    headers={"Range": "bytes=0-4095"},
                )
                try:
                    try:
                        status = int(resp.status_code)
                    except Exception:
                        status = 0
                    if status not in {200, 206}:
                        return _cache(False, f"get:{status or 'error'}")

                    first_chunk = b""
                    try:
                        for chunk in resp.iter_content(chunk_size=4096):
                            if chunk:
                                first_chunk = bytes(chunk[:4096])
                                break
                    except Exception:
                        first_chunk = b""

                    if _looks_like_pdf_bytes(first_chunk):
                        return _cache(True, "get:pdf_signature")
                    if _looks_like_html_bytes(first_chunk):
                        return _cache(False, "get:html_signature")

                    content_type = resp.headers.get("content-type", "")
                    if _content_type_indicates_pdf(content_type):
                        return _cache(True, "get:pdf_content_type")
                    if _content_type_indicates_html(content_type):
                        return _cache(False, "get:html_content_type")
                    return _cache(False, "get:unknown")
                finally:
                    cls._safe_close_response(resp)
            except Exception:
                return _cache(False, "get:error")
        finally:
            cls._release_url_probe_slot(target)

    @classmethod
    def _search_bestexamhelp(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        results = []
        level_slug = SubjectDatabase.get_bestexamhelp_track(subject_code)

        subject_folder = get_subject_folder(subject_code)
        full_year = "20" + str(year) if len(str(year)) == 2 else str(year)

        target_component = str(component or "").strip()
        if not target_component:
            return results

        resolved_component_hint = ""
        for raw_doc_type in doc_types:
            doc_type = str(raw_doc_type or "").strip().upper()
            if not doc_type:
                continue
            doc_type_for_result = "QP" if doc_type == "P" else doc_type
            if doc_type_for_result == "GT":
                probe_components = [target_component]
            else:
                probe_components = cls._component_probe_order(subject_code, target_component)
                if resolved_component_hint and resolved_component_hint in probe_components:
                    probe_components = [resolved_component_hint] + [
                        comp for comp in probe_components
                        if comp != resolved_component_hint
                    ]
                max_probes = max(1, int(cls.BESTEXAMHELP_MAX_COMPONENT_PROBES))
                probe_components = probe_components[:max_probes]
            for probe_component in probe_components:
                filename = cls._build_filename(subject_code, series, year, doc_type_for_result, probe_component)
                relative = cls._safe_join_path(level_slug, subject_folder, full_year, f"{filename}.pdf")
                url = f"{cls.SOURCES['bestexamhelp']['base_url'].rstrip('/')}/{relative}"
                if not cls._url_exists(url):
                    continue
                results.append(
                    cls._format_result(
                        subject_code,
                        year,
                        series,
                        (probe_component if doc_type_for_result != "GT" else target_component),
                        doc_type_for_result,
                        filename,
                        url,
                        "bestexamhelp",
                    )
                )
                cls._learn_component_style(subject_code, probe_component)
                resolved_component_hint = str(probe_component or "").strip()
                break

        return results

    @classmethod
    def _search_papacambridge(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        target_component = str(component or "").strip()
        if not target_component:
            return []

        # Mission-critical path: direct hardcoded URL probing first.
        direct_hits = cls._search_papacambridge_hardcoded_direct(
            subject_code=subject_code,
            year=year,
            series=series,
            component=target_component,
            doc_types=doc_types,
        )
        if direct_hits:
            return direct_hits

        return cls._search_papacambridge_listing_fallback(
            subject_code=subject_code,
            year=year,
            series=series,
            component=target_component,
            doc_types=doc_types,
        )

    @classmethod
    def _search_papacambridge_hardcoded_direct(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        target_component = str(component or "").strip()
        if not target_component:
            return []

        results: List[Dict] = []
        upload_bases = cls._pastpapersco_upload_bases()
        unreachable_bases: set[str] = set()
        for raw_doc_type in doc_types:
            doc_type = str(raw_doc_type or "").strip().upper()
            if not doc_type:
                continue
            doc_type_for_result = "QP" if doc_type == "P" else doc_type

            probe_components = (
                [target_component]
                if doc_type == "GT"
                else cls._component_probe_order(subject_code, target_component)
            )
            for probe_component in probe_components:
                if len(unreachable_bases) >= len(upload_bases):
                    break
                found = False
                for base_url in upload_bases:
                    if base_url in unreachable_bases:
                        continue
                    filename = cls._build_filename(subject_code, series, year, doc_type, probe_component)
                    direct_url = f"{base_url}/{filename}.pdf"
                    success, status = cls._pastpapersco_asset_probe(direct_url)
                    cls._log_event(
                        "source.probe",
                        source="pastpapersco",
                        subject=subject_code,
                        series=series,
                        year=year,
                        doc_type=doc_type_for_result,
                        component=probe_component,
                        status=status,
                        exists=bool(success),
                    )
                    if success:
                        cls._pastpapersco_preferred_base = base_url
                        cls._url_probe_cache_put(direct_url, True, "direct:success")
                        file_stem = os.path.splitext(os.path.basename(urlsplit(direct_url).path))[0]
                        results.append(
                            cls._format_result(
                                subject_code=subject_code,
                                year=year,
                                series=series,
                                component=(target_component if doc_type == "GT" else probe_component),
                                doc_type=doc_type_for_result,
                                filename=file_stem,
                                url=direct_url,
                                source="pastpapersco",
                                direct_url=direct_url,
                                viewer_url="",
                                extension="pdf",
                            )
                        )
                        cls._learn_component_style(subject_code, probe_component)
                        found = True
                        break
                    if status == 0:
                        cls._url_probe_cache_drop(direct_url)
                        unreachable_bases.add(base_url)
                        continue
                    cls._url_probe_cache_put(direct_url, False, f"direct:{status}")

                    # Missing/denied usually means this component variant does not
                    # exist; move to next component instead of probing extra bases.
                    if status in {403, 404}:
                        break
                    # Mirror host usually yields identical 2xx wrapper response.
                    if 200 <= status < 300:
                        break
                if found:
                    break
        return results

    @classmethod
    def _papacambridge_doc_token_matches_type(cls, doc_token: str, doc_type: str) -> bool:
        token = str(doc_token or "").strip().lower()
        wanted = "QP" if str(doc_type or "").strip().upper() == "P" else str(doc_type or "").strip().upper()
        if wanted == "QP":
            return token in {"qp", "question_paper", "question-paper"}
        if wanted == "MS":
            return token in {"ms", "mark_scheme", "mark-scheme", "markscheme"}
        if wanted == "GT":
            return token in {"gt", "grade_threshold", "grade-threshold", "threshold"}
        return token == wanted.lower()

    @classmethod
    def _search_papacambridge_listing_fallback(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        refs = cls._papacambridge_docs_for_series(subject_code=subject_code, year=year, series=series)
        if not refs:
            return []

        target_component = str(component or "").strip()
        if not target_component:
            return []

        results: List[Dict] = []
        seen_urls: set[str] = set()
        for raw_doc_type in doc_types:
            doc_type = str(raw_doc_type or "").strip().upper()
            if not doc_type:
                continue
            normalized_type = "QP" if doc_type == "P" else doc_type
            probe_components = (
                [target_component]
                if normalized_type == "GT"
                else cls._component_probe_order(subject_code, target_component)
            )

            matched = False
            for probe_component in probe_components:
                for ref in refs:
                    if not cls._papacambridge_doc_token_matches_type(ref.doc_token, normalized_type):
                        continue
                    ref_component = str(ref.component or "").strip()
                    if normalized_type == "GT":
                        if ref_component and not cls._papacambridge_components_match(target_component, ref_component):
                            continue
                    else:
                        if ref_component and not cls._papacambridge_components_match(probe_component, ref_component):
                            continue
                    direct_url = str(ref.direct_url or "").strip()
                    if not direct_url:
                        continue
                    if direct_url in seen_urls:
                        continue
                    seen_urls.add(direct_url)
                    stem = os.path.splitext(str(ref.filename or "").strip())[0]
                    if not stem:
                        stem = os.path.splitext(os.path.basename(urlsplit(direct_url).path))[0]
                    ext = os.path.splitext(str(ref.filename or "").strip())[1].lower().lstrip(".")
                    results.append(
                        cls._format_result(
                            subject_code=subject_code,
                            year=year,
                            series=series,
                            component=(target_component if normalized_type == "GT" else (ref_component or probe_component)),
                            doc_type=normalized_type,
                            filename=stem,
                            url=direct_url,
                            source="papacambridge",
                            direct_url=direct_url,
                            viewer_url=str(ref.viewer_url or "").strip(),
                            extension=ext or "pdf",
                        )
                    )
                    cls._learn_component_style(subject_code, ref_component or probe_component)
                    matched = True
                    break
                if matched:
                    break
        return results

    @staticmethod
    def _component_digits(component: str) -> str:
        raw = str(component or "").strip()
        return "".join(ch for ch in raw if ch.isdigit())[:2]

    @classmethod
    def _papacambridge_component_paper(cls, component: str) -> str:
        digits = cls._component_digits(component)
        if not digits:
            return ""
        if len(digits) == 1:
            return digits[0]
        if digits[0] == "0":
            return digits[1]
        return digits[0]

    @classmethod
    def _papacambridge_component_variant(cls, component: str) -> str:
        digits = cls._component_digits(component)
        if len(digits) < 2:
            return "0"
        if digits[0] == "0":
            return "0"
        return digits[1]

    @classmethod
    def _papacambridge_component_fallbacks(cls, component: str) -> List[str]:
        raw = str(component or "").strip()
        digits = cls._component_digits(raw)
        out: List[str] = []
        seen: set[str] = set()

        def _add(value: str) -> None:
            text = str(value or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            out.append(text)

        _add(raw)
        paper = cls._papacambridge_component_paper(raw)
        if paper:
            _add(paper)
            _add(f"0{paper}")
            # Prefer the requested paper/variant pair, then probe neighboring
            # variant slots because many archives normalize or reshuffle variants.
            variant_order: List[str] = []
            if len(digits) >= 2 and digits[0] != "0":
                requested_variant = digits[1]
                if requested_variant.isdigit():
                    variant_order.append(requested_variant)
                    for alt in ("1", "2", "3"):
                        if alt != requested_variant:
                            variant_order.append(alt)
            else:
                variant_order = ["1", "2", "3"]
            for variant in variant_order:
                _add(f"{paper}{variant}")
        return out

    @classmethod
    def _component_style_cache_key(cls, subject_code: str, paper_number: str) -> str:
        return f"{str(subject_code or '').strip()}|{str(paper_number or '').strip()}"

    @classmethod
    def _component_style_for_paper(cls, subject_code: str, paper_number: str) -> str:
        key = cls._component_style_cache_key(subject_code, paper_number)
        entry = cls._component_style_cache.get(key)
        if not isinstance(entry, dict):
            return ""
        checked_at = cls._coerce_timestamp(entry.get("checked_at", 0.0))
        ttl = max(60, int(cls.COMPONENT_CACHE_TTL_SECONDS))
        if checked_at <= 0.0 or (cls._now_ts() - checked_at) > ttl:
            cls._component_style_cache.pop(key, None)
            return ""
        style = str(entry.get("style", "")).strip().lower()
        if style not in {"zero_padded", "variant"}:
            return ""
        return style

    @classmethod
    def _learn_component_style(cls, subject_code: str, component: str) -> None:
        token = cls._component_digits(component)
        if not token:
            return
        if re.fullmatch(r"0[1-9]", token):
            style = "zero_padded"
        elif re.fullmatch(r"[1-9][1-3]", token):
            style = "variant"
        else:
            return
        paper_number = cls._papacambridge_component_paper(token)
        if not paper_number:
            return
        key = cls._component_style_cache_key(subject_code, paper_number)
        cls._component_style_cache[key] = {
            "style": style,
            "checked_at": cls._now_ts(),
        }
        cls._prune_cache_by_size(cls._component_style_cache, 4000)

    @classmethod
    def _component_probe_order(cls, subject_code: str, component: str) -> List[str]:
        requested = str(component or "").strip()
        if not requested:
            return []
        candidates = cls._papacambridge_component_fallbacks(requested)
        if not candidates:
            return [requested]

        paper_number = cls._papacambridge_component_paper(requested)
        cached_style = cls._component_style_for_paper(subject_code, paper_number) if paper_number else ""

        zero_padded: List[str] = []
        variants: List[str] = []
        others: List[str] = []
        for candidate in candidates:
            digits = cls._component_digits(candidate)
            if re.fullmatch(r"0[1-9]", digits):
                zero_padded.append(candidate)
            elif re.fullmatch(r"[1-9][1-3]", digits):
                variants.append(candidate)
            else:
                others.append(candidate)

        if cached_style == "variant":
            ordered = variants + zero_padded + others
        else:
            # Default unknown style: prefer 0x probes first.
            ordered = zero_padded + variants + others

        deduped: List[str] = []
        seen: set[str] = set()
        for candidate in ordered:
            value = str(candidate or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped or candidates

    @classmethod
    def _papacambridge_components_match(cls, requested_component: str, actual_component: str) -> bool:
        requested = str(requested_component or "").strip()
        actual = str(actual_component or "").strip()
        if not requested or not actual:
            return False
        if requested == actual:
            return True
        req_paper = cls._papacambridge_component_paper(requested)
        act_paper = cls._papacambridge_component_paper(actual)
        if not req_paper or not act_paper or req_paper != act_paper:
            return False
        req_variant = cls._papacambridge_component_variant(requested)
        act_variant = cls._papacambridge_component_variant(actual)
        if act_variant == "0":
            return True
        return req_variant == act_variant

    @staticmethod
    def _coerce_full_year(year_text: str) -> str:
        raw = str(year_text or "").strip()
        if not raw:
            return str(datetime.now().year)
        if len(raw) == 2 and raw.isdigit():
            return f"20{raw}"
        match = re.search(r"(20\d{2})", raw)
        if match:
            return match.group(1)
        return raw

    @classmethod
    def _papacambridge_docs_for_series(
        cls,
        subject_code: str,
        year: str,
        series: str,
    ) -> List[PapacambridgeDocRef]:
        if not cls.ENABLE_PASTPAPERSCO_LISTING_FALLBACK:
            return []

        session = str(series or "").strip().upper()
        session_slug = cls.PAPACAMBRIDGE_SESSION_SLUGS.get(session)
        if not session_slug:
            return []

        year_full = cls._coerce_full_year(year)
        cache_key = f"{subject_code}|{year_full}|{session}"
        cached_refs = cls._papacambridge_docs_cache.get(cache_key)
        if cached_refs:
            return list(cached_refs)

        subject_slug = cls._resolve_papacambridge_subject_slug(subject_code)
        if not subject_slug:
            cls._log_event(
                "source.fallback",
                source="papacambridge",
                subject=subject_code,
                reason="subject_slug_missing",
            )
            cls._papacambridge_docs_cache.pop(cache_key, None)
            return []

        listing_url = (
            "https://pastpapers.papacambridge.com/papers/caie/"
            f"{subject_slug}-{year_full}-{session_slug}"
        )
        refs = cls._parse_papacambridge_year_listing(
            listing_url=listing_url,
            subject_code=subject_code,
            expected_year=year_full,
            expected_session=session,
        )
        if not refs:
            cls._log_event(
                "source.fallback",
                source="papacambridge",
                subject=subject_code,
                reason="listing_empty",
                listing_url=listing_url,
            )
        if refs:
            cls._papacambridge_docs_cache[cache_key] = list(refs)
        else:
            cls._papacambridge_docs_cache.pop(cache_key, None)
        return refs

    @classmethod
    def _resolve_papacambridge_subject_slug(cls, subject_code: str) -> str:
        subject = str(subject_code or "").strip()
        if not subject:
            return ""
        level = SubjectDatabase.get_exam_level(subject)
        index_url = cls.PAPACAMBRIDGE_INDEX_URLS.get(level)
        if not index_url:
            return ""

        cache_key = f"{level}|{subject}"
        cached = cls._papacambridge_subject_slug_cache.get(cache_key)
        if cached:
            return cached

        try:
            html = cls._http_get_text(index_url, timeout=cls.PAPACAMBRIDGE_LISTING_TIMEOUT_SECONDS)
        except Exception:
            cls._papacambridge_subject_slug_cache[cache_key] = ""
            return ""

        anchor_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        candidates: List[Tuple[int, str]] = []
        subject_norm = re.sub(r"[^a-z0-9]", "", subject.lower())
        for href, label_html in anchor_pattern.findall(html):
            url = urljoin(index_url, href)
            path = urlsplit(url).path
            if "/papers/caie/" not in path:
                continue
            slug = path.rstrip("/").split("/")[-1]
            if not slug:
                continue
            label = re.sub(r"<[^>]+>", " ", label_html or "")
            haystack = re.sub(r"[^a-z0-9]", "", f"{slug} {label}".lower())
            if subject_norm not in haystack:
                continue
            score = 0
            if subject_norm in re.sub(r"[^a-z0-9]", "", slug.lower()):
                score += 5
            if f"-{subject}" in slug or slug.endswith(subject):
                score += 2
            candidates.append((score, slug))

        if candidates:
            candidates.sort(key=lambda row: (-row[0], len(row[1])))
            resolved = candidates[0][1]
            cls._papacambridge_subject_slug_cache[cache_key] = resolved
            return resolved

        cls._papacambridge_subject_slug_cache[cache_key] = ""
        return ""

    @classmethod
    def list_papacambridge_subjects(cls, level: str) -> Dict[str, str]:
        if not cls.ENABLE_PASTPAPERSCO_LISTING_FALLBACK:
            return {}

        level_key = "A Level" if str(level or "").strip().lower().startswith("a") else "IGCSE"
        index_url = cls.PAPACAMBRIDGE_INDEX_URLS.get(level_key)
        if not index_url:
            return {}

        try:
            html = cls._http_get_text(index_url, timeout=cls.PAPACAMBRIDGE_LISTING_TIMEOUT_SECONDS)
        except Exception:
            return {}

        out: Dict[str, str] = {}
        anchor_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
        for href, label_html in anchor_pattern.findall(html):
            url = urljoin(index_url, href)
            path = urlsplit(url).path
            if "/papers/caie/" not in path:
                continue

            label = re.sub(r"<[^>]+>", " ", label_html or "")
            label = re.sub(r"\s+", " ", label).strip()
            code_match = re.search(r"\b(\d{4})\b", f"{label} {path}")
            if not code_match:
                continue
            code = code_match.group(1)

            cleaned = re.sub(r"\(\s*\d{4}\s*\)", "", label)
            cleaned = re.sub(r"\b\d{4}\b", "", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_\t")
            if not cleaned:
                slug = path.rstrip("/").split("/")[-1]
                slug = slug.replace("igcse-", "").replace("as-and-a-level-", "")
                cleaned = re.sub(r"[-_]+", " ", slug)
                cleaned = re.sub(r"\b\d{4}\b", "", cleaned).strip()

            if cleaned:
                out[code] = cleaned.title()
        return out

    @classmethod
    def _parse_papacambridge_year_listing(
        cls,
        listing_url: str,
        subject_code: str,
        expected_year: str,
        expected_session: str,
    ) -> List[PapacambridgeDocRef]:
        entries: Dict[str, Dict[str, str]] = {}
        fallback_urls: List[str] = []
        try:
            html = cls._http_get_text(listing_url, timeout=cls.PAPACAMBRIDGE_LISTING_TIMEOUT_SECONDS)
        except Exception:
            html = ""
        if html:
            entries, fallback_urls = cls._extract_papacambridge_entries_from_html(
                html=html,
                page_url=listing_url,
                subject_code=subject_code,
                expected_year=expected_year,
                expected_session=expected_session,
            )

        if not entries:
            cls._log_event(
                "source.fallback",
                source="papacambridge",
                subject=subject_code,
                reason="primary_listing_empty",
            )
            entries = cls._crawl_papacambridge_listing_tree(
                seed_urls=fallback_urls or [listing_url],
                subject_code=subject_code,
                expected_year=expected_year,
                expected_session=expected_session,
            )

        refs: List[PapacambridgeDocRef] = []
        upload_base = cls._pastpapersco_upload_bases()[0]
        expected_year_int = cls._coerce_year_int(expected_year)
        expected_session_norm = str(expected_session or "").strip().upper()
        for row in entries.values():
            filename = str(row.get("filename", "")).strip()
            direct_url = str(row.get("direct_url", "")).strip()
            viewer_url = str(row.get("viewer_url", "")).strip()
            # Prefer listing-derived direct URLs when present; only synthesize as fallback.
            if not direct_url and filename:
                direct_url = f"{upload_base}/{filename}"
            if not direct_url:
                continue

            meta = cls._parse_papacambridge_filename_meta(filename, subject_code)
            if not meta:
                continue

            year_int = cls._coerce_year_int(str(meta.get("year", "")))
            if expected_year_int and year_int and year_int != expected_year_int:
                continue

            session = str(meta.get("session", "")).upper()
            if expected_session_norm and session and session != expected_session_norm:
                continue

            refs.append(
                PapacambridgeDocRef(
                    filename=filename,
                    subject_code=str(meta.get("subject_code", "")),
                    year=str(meta.get("year", "")),
                    session=session,
                    component=str(meta.get("component", "")),
                    doc_token=str(meta.get("doc_token", "")),
                    direct_url=direct_url,
                    viewer_url=viewer_url,
                )
            )

        return refs

    @classmethod
    def _merge_papacambridge_entries(
        cls,
        target: Dict[str, Dict[str, str]],
        incoming: Dict[str, Dict[str, str]],
    ) -> None:
        for key, row in incoming.items():
            filename = str(row.get("filename", "")).strip()
            if not filename:
                continue
            existing = target.setdefault(key, {"filename": filename, "direct_url": "", "viewer_url": ""})
            direct = str(row.get("direct_url", "")).strip()
            viewer = str(row.get("viewer_url", "")).strip()
            if direct:
                existing["direct_url"] = direct
            if viewer:
                existing["viewer_url"] = viewer

    @classmethod
    def _crawl_papacambridge_listing_tree(
        cls,
        seed_urls: List[str],
        subject_code: str,
        expected_year: str,
        expected_session: str,
    ) -> Dict[str, Dict[str, str]]:
        max_depth = 1
        max_pages = 4
        queue: List[Tuple[str, int]] = [(str(url or "").strip(), 0) for url in seed_urls if str(url or "").strip()]
        visited: set[str] = set()
        entries: Dict[str, Dict[str, str]] = {}

        while queue and len(visited) < max_pages:
            page_url, depth = queue.pop(0)
            normalized = cls._normalize_web_url(page_url)
            if not normalized or normalized in visited:
                continue
            visited.add(normalized)

            cls._log_event(
                "source.fallback",
                source="papacambridge",
                subject=subject_code,
                reason="crawl",
                depth=depth,
                page_url=page_url,
            )

            try:
                html = cls._http_get_text(page_url, timeout=cls.PAPACAMBRIDGE_LISTING_TIMEOUT_SECONDS)
            except Exception:
                html = ""
            if not html:
                continue

            page_entries, child_urls = cls._extract_papacambridge_entries_from_html(
                html=html,
                page_url=page_url,
                subject_code=subject_code,
                expected_year=expected_year,
                expected_session=expected_session,
            )
            cls._merge_papacambridge_entries(entries, page_entries)

            if depth >= max_depth:
                continue
            for child_url in child_urls:
                child_norm = cls._normalize_web_url(child_url)
                if not child_norm or child_norm in visited:
                    continue
                queue.append((child_url, depth + 1))

        return entries

    @staticmethod
    def _normalize_web_url(url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            return ""
        parts = urlsplit(raw)
        path = re.sub(r"/+", "/", parts.path or "/")
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))

    @classmethod
    def _papacambridge_session_tokens(cls, expected_session: str) -> set[str]:
        session = str(expected_session or "").strip().upper()
        tokens: set[str] = set()
        if session:
            tokens.add(session.lower())
        slug = cls.PAPACAMBRIDGE_SESSION_SLUGS.get(session, "")
        if slug:
            tokens.add(slug.lower())
            for piece in slug.split("-"):
                piece_norm = str(piece).strip().lower()
                if piece_norm:
                    tokens.add(piece_norm)
        if session == "MJ":
            tokens.update({"may", "june"})
        elif session == "ON":
            tokens.update({"october", "november", "oct", "nov"})
        elif session == "FM":
            tokens.update({"february", "march", "feb", "mar"})
        return tokens

    @classmethod
    def _is_papacambridge_document_href(cls, url: str) -> bool:
        lower_href = str(url or "").strip().lower()
        if not lower_href:
            return False
        if lower_href.endswith(".pdf"):
            return True
        return (
            "/viewer/caie/" in lower_href
            or "download_file.php" in lower_href
            or "/upload/" in lower_href
        )

    @classmethod
    def _is_papacambridge_navigation_href(
        cls,
        url: str,
        subject_code: str,
        expected_year: str,
        expected_session: str,
    ) -> bool:
        raw = str(url or "").strip()
        if not raw:
            return False
        lowered = raw.lower()
        if lowered.startswith(("javascript:", "mailto:", "#")):
            return False
        if cls._is_papacambridge_document_href(raw):
            return False

        parts = urlsplit(raw)
        host = parts.netloc.lower()
        if "papacambridge.com" not in host:
            return False

        path = parts.path.lower()
        if "/papers/caie/" not in path and "/directories/caie/" not in path:
            return False

        haystack = f"{path} {parts.query}".lower()
        subject = str(subject_code or "").strip().lower()
        year_full = cls._coerce_full_year(expected_year)
        year_tokens = {year_full.lower(), year_full[-2:].lower()} if year_full else set()
        session_tokens = cls._papacambridge_session_tokens(expected_session)

        subject_match = bool(subject and subject in haystack)
        year_match = bool(year_tokens and any(token in haystack for token in year_tokens))
        session_match = bool(session_tokens and any(token in haystack for token in session_tokens))
        return bool(subject_match or year_match or session_match or "/papers/caie/" in path)

    @classmethod
    def _add_papacambridge_entry_from_href(
        cls,
        entries: Dict[str, Dict[str, str]],
        page_url: str,
        href: str,
    ) -> bool:
        full_href = urljoin(page_url, str(href or "").strip())
        if not cls._is_papacambridge_document_href(full_href):
            return False

        lower_href = full_href.lower()
        is_viewer = "/viewer/caie/" in lower_href
        direct_url = ""
        viewer_url = ""

        if is_viewer:
            viewer_url = full_href
            filename = os.path.basename(urlsplit(full_href).path)
        else:
            direct_url = cls._extract_papacambridge_direct_from_download_href(full_href)
            filename = os.path.basename(urlsplit(direct_url).path) if direct_url else ""

        if not filename:
            return False

        key = cls._normalize_file_key(filename)
        row = entries.setdefault(key, {"filename": filename, "direct_url": "", "viewer_url": ""})
        if direct_url:
            row["direct_url"] = direct_url
        if viewer_url:
            row["viewer_url"] = viewer_url
        return True

    @classmethod
    def _extract_papacambridge_entries_from_html(
        cls,
        html: str,
        page_url: str,
        subject_code: str,
        expected_year: str,
        expected_session: str,
    ) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
        entries: Dict[str, Dict[str, str]] = {}
        fallback_urls: List[str] = []
        fallback_seen: set[str] = set()
        html_text = str(html or "")

        href_pattern = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
        row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)

        def _add_fallback(url: str) -> None:
            full_url = urljoin(page_url, str(url or "").strip())
            if not cls._is_papacambridge_navigation_href(full_url, subject_code, expected_year, expected_session):
                return
            normalized = cls._normalize_web_url(full_url)
            if not normalized or normalized in fallback_seen:
                return
            fallback_seen.add(normalized)
            fallback_urls.append(full_url)

        # Prefer row parsing first because PapaCambridge listings are table-based.
        for row_html in row_pattern.findall(html_text):
            row_hrefs = href_pattern.findall(row_html)
            for href in row_hrefs:
                if cls._add_papacambridge_entry_from_href(entries, page_url, href):
                    continue
                _add_fallback(href)

        # Backup parse for pages where links are not inside <tr>.
        for href in href_pattern.findall(html_text):
            if cls._add_papacambridge_entry_from_href(entries, page_url, href):
                continue
            _add_fallback(href)

        # Some templates embed URLs in attributes/scripts instead of href anchors.
        embedded_url_patterns = [
            r"(?:https?:)?//[^\"'<>\\s]*papacambridge\\.com[^\"'<>\\s]*download_file\\.php\\?[^\"'<>\\s]+",
            r"(?:https?:)?//[^\"'<>\\s]*papacambridge\\.com[^\"'<>\\s]*/viewer/caie/[^\"'<>\\s]+",
            r"(?:https?:)?//[^\"'<>\\s]*papacambridge\\.com[^\"'<>\\s]*/directories/CAIE/CAIE-pastpapers/upload/[^\"'<>\\s]+",
            r"/papers/caie/download_file\\.php\\?[^\"'<>\\s]+",
            r"/viewer/caie/[^\"'<>\\s]+",
            r"/directories/CAIE/CAIE-pastpapers/upload/[^\"'<>\\s]+",
        ]
        for pattern in embedded_url_patterns:
            for embedded in re.findall(pattern, html_text, flags=re.IGNORECASE):
                if cls._add_papacambridge_entry_from_href(entries, page_url, embedded):
                    continue
                _add_fallback(embedded)

        return entries, fallback_urls

    @classmethod
    def _parse_papacambridge_filename_meta(cls, filename: str, subject_code: str) -> Optional[Dict[str, str]]:
        name = os.path.basename(str(filename or "").strip())
        match = re.match(
            r"^(?P<subject>\d{4})_(?P<series>[a-z])(?P<yy>\d{2})_(?P<token>[a-z]+(?:_[a-z]+)*)(?:_(?P<component>\d{1,2}))?\.(?P<ext>[a-z0-9]+)$",
            name,
            re.IGNORECASE,
        )
        if not match:
            return None
        groups = match.groupdict()
        if str(groups.get("subject", "")) != str(subject_code):
            return None

        series_code = str(groups.get("series", "")).lower()
        session = {"s": "MJ", "w": "ON", "m": "FM"}.get(series_code, "")
        if not session:
            return None

        yy = str(groups.get("yy", "")).strip()
        year_full = f"20{yy}" if yy.isdigit() else ""
        token = str(groups.get("token", "")).strip().lower()
        raw_component = groups.get("component")
        component = str(raw_component or "").strip()
        ext = str(groups.get("ext", "")).strip().lower()
        if not (year_full and token and ext):
            return None

        return {
            "subject_code": str(subject_code),
            "year": year_full,
            "session": session,
            "doc_token": token,
            "component": component,
            "extension": ext,
        }

    @staticmethod
    def _extract_papacambridge_direct_from_download_href(href: str) -> str:
        url = str(href or "").strip()
        if not url:
            return ""
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        for key in ("files", "file", "url", "download"):
            values = query.get(key, [])
            if not values:
                continue
            candidate = unquote(str(values[0] or "").strip())
            if not candidate:
                continue
            if candidate.startswith("http"):
                return candidate
            return urljoin(url, candidate)
        if parts.path.lower().endswith(".pdf"):
            return url
        if "/upload/" in parts.path.lower():
            return url
        return ""

    @classmethod
    def _classify_resource_family(cls, token: str, extension: str) -> str:
        token_norm = str(token or "").strip().lower()
        ext = str(extension or "").strip().lower().lstrip(".")
        if (
            "_in_" in f"_{token_norm}_"
            or "insert" in token_norm
            or "passage" in token_norm
            or token_norm in {"rp", "qr"}
        ) and ext == "pdf":
            return "INSERT"
        if (token_norm in {"sf", "au"} or "audio" in token_norm or "listening" in token_norm) and ext in {"mp3", "m4a", "wav"}:
            return "AUDIO"
        if (token_norm == "sf" or "source" in token_norm) and ext == "zip":
            return "SOURCE_FILE"
        if (token_norm == "tn" or "transcript" in token_norm) and ext == "pdf":
            return "TRANSCRIPT"
        if token_norm.startswith("map") and ext == "pdf":
            return "MAP"
        family = cls.TOKEN_TO_FAMILY.get(token_norm, "")
        if family:
            return family
        return "OTHER"

    @staticmethod
    def _paper_number_from_component(component: str) -> Optional[int]:
        text = str(component or "").strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return None
        if len(digits) >= 2 and digits[0] == "0":
            try:
                return int(digits[1])
            except Exception:
                return None
        try:
            return int(digits[0])
        except Exception:
            return None

    @classmethod
    def _is_listening_component(cls, subject_code: str, component: str) -> bool:
        code = str(subject_code or "").strip()
        paper = normalize_paper_number(component)
        if not code or not paper:
            return False
        row = get_subject_row(code, paper)
        if not isinstance(row, dict):
            return False
        flags = row.get("flags") if isinstance(row.get("flags"), dict) else {}
        if not isinstance(flags, dict):
            return False
        if not bool(flags.get("is_listening")):
            return False
        if bool(flags.get("is_speaking_or_oral")):
            return False
        return True

    @classmethod
    def _resource_allowed_for_subject(cls, subject_code: str, component: str, family: str) -> bool:
        family_norm = str(family or "").strip().upper()
        if family_norm in {"", "OTHER"}:
            return False

        if family_norm in {"AUDIO", "TRANSCRIPT"} and cls._is_listening_component(subject_code, component):
            return True

        subject = str(subject_code or "").strip()
        policy = cls.SUBJECT_RESOURCE_POLICIES.get(subject)
        if not policy:
            return family_norm in {"INSERT", "SOURCE_FILE", "MAP"}

        allowed_families = set(policy.get("families", set()))
        if family_norm not in allowed_families:
            return False

        allowed_papers = policy.get("papers")
        if isinstance(allowed_papers, set) and allowed_papers:
            paper_num = cls._paper_number_from_component(component)
            if paper_num is None:
                return False
            return paper_num in allowed_papers
        return True

    @classmethod
    def _resolve_open_download_urls(cls, direct_url: str, viewer_url: str, extension: str) -> Tuple[str, str]:
        direct = str(direct_url or "").strip()
        _ = str(viewer_url or "").strip()
        _ = str(extension or "").strip().lower().lstrip(".")
        if not direct:
            return ("", "")
        # Always prefer the direct asset URL for open/download.
        return (direct, direct)

    @classmethod
    def _search_gceguide(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        results = []
        catalog = cls._collect_source_pdf_catalog("gceguide", subject_code)
        if not catalog:
            return results

        seen_urls: set[str] = set()
        for doc_type in doc_types:
            normalized_type = "QP" if str(doc_type).upper() == "P" else str(doc_type).upper()
            probe_components = (
                [str(component)]
                if normalized_type == "GT"
                else cls._papacambridge_component_fallbacks(str(component))
            )
            for probe_component in probe_components:
                filename = cls._build_filename(subject_code, series, year, normalized_type, probe_component) + ".pdf"
                pdf_url = str(catalog.get(cls._normalize_file_key(filename), "")).strip()
                if not pdf_url:
                    continue
                if pdf_url in seen_urls:
                    continue
                if not cls._url_exists(pdf_url):
                    continue
                seen_urls.add(pdf_url)
                results.append(
                    cls._format_result(
                        subject_code,
                        year,
                        series,
                        component if normalized_type == "GT" else probe_component,
                        normalized_type,
                        filename[:-4],
                        pdf_url,
                        "gceguide",
                    )
                )
                break

        return results

    @classmethod
    def _search_dynamicpapers(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_types: List[str],
    ) -> List[Dict]:
        results = []
        catalog = cls._collect_source_pdf_catalog("dynamicpapers", subject_code)
        if not catalog:
            return results

        seen_urls: set[str] = set()
        for doc_type in doc_types:
            normalized_type = "QP" if str(doc_type).upper() == "P" else str(doc_type).upper()
            probe_components = (
                [str(component)]
                if normalized_type == "GT"
                else cls._papacambridge_component_fallbacks(str(component))
            )
            for probe_component in probe_components:
                filename = cls._build_filename(subject_code, series, year, normalized_type, probe_component) + ".pdf"
                pdf_url = str(catalog.get(cls._normalize_file_key(filename), "")).strip()
                if not pdf_url:
                    continue
                if pdf_url in seen_urls:
                    continue
                if not cls._url_exists(pdf_url):
                    continue
                seen_urls.add(pdf_url)
                results.append(
                    cls._format_result(
                        subject_code,
                        year,
                        series,
                        component if normalized_type == "GT" else probe_component,
                        normalized_type,
                        filename[:-4],
                        pdf_url,
                        "dynamicpapers",
                    )
                )
                break

        return results

    @classmethod
    def _search_specimen_multi_source(
        cls,
        subject_code: str,
        components: List[str],
        doc_types: List[str],
        source_order: List[str],
    ) -> List[Dict]:
        paper_numbers = cls._extract_paper_numbers(components)
        if not paper_numbers:
            return []

        all_items: List[Dict] = []
        seen_urls: set[str] = set()

        for source_name in source_order:
            source_items = cls._search_specimen_from_source(source_name, subject_code, paper_numbers, doc_types)
            for item in source_items:
                url = str(item.get("url", "")).strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_items.append(item)

        latest: Dict[Tuple[str, str, str], Dict] = {}
        for item in all_items:
            key = (
                str(item.get("subject_code", "")).strip(),
                str(item.get("component", "")).strip(),
                str(item.get("type", "")).strip().upper(),
            )
            current = latest.get(key)
            if current is None:
                latest[key] = item
                continue
            if cls._coerce_year_int(str(item.get("year", ""))) >= cls._coerce_year_int(str(current.get("year", ""))):
                latest[key] = item

        return list(latest.values())

    @classmethod
    def _search_specimen_from_source(
        cls,
        source_name: str,
        subject_code: str,
        paper_numbers: List[str],
        doc_types: List[str],
    ) -> List[Dict]:
        results: List[Dict] = []
        requested = {str(dt).upper() for dt in doc_types}
        want_qp = bool({"QP", "P"} & requested)
        want_ms = "MS" in requested

        catalog = cls._collect_source_pdf_catalog(source_name, subject_code)
        if catalog:
            for filename, url in catalog.items():
                meta = cls._extract_specimen_meta_from_filename(filename, subject_code)
                if not meta:
                    continue
                paper = meta["paper"]
                if paper_numbers and str(paper) not in set(paper_numbers):
                    continue
                if meta["kind"] == "SP_QP" and not want_qp:
                    continue
                if meta["kind"] == "SP_MS" and not want_ms:
                    continue
                results.append(
                    cls._format_specimen_result(
                        subject_code=subject_code,
                        year=meta["year"],
                        component=paper,
                        filename=os.path.splitext(filename)[0],
                        url=url,
                        source=source_name,
                        kind=meta["kind"],
                    )
                )

        if source_name in {"papacambridge", "pastpapersco"}:
            base_url = cls._pastpapersco_upload_bases()[0]
            recent_years = cls._specimen_candidate_years()
            for yy in recent_years:
                for paper in paper_numbers:
                    if want_qp:
                        stem = f"{subject_code}_y{yy}_sp_{paper}"
                        url = f"{base_url}/{stem}.pdf"
                        if cls._url_exists(url):
                            results.append(cls._format_specimen_result(subject_code, str(2000 + int(yy)), paper, stem, url, source_name, "SP_QP"))
                    if want_ms:
                        stem = f"{subject_code}_y{yy}_sm_{paper}"
                        url = f"{base_url}/{stem}.pdf"
                        if cls._url_exists(url):
                            results.append(cls._format_specimen_result(subject_code, str(2000 + int(yy)), paper, stem, url, source_name, "SP_MS"))

        return results

    @classmethod
    def _collect_source_pdf_catalog(cls, source_name: str, subject_code: str) -> Dict[str, str]:
        cache_key = f"{source_name}|{subject_code}"
        cache_entry = cls._source_pdf_catalog_cache.get(cache_key)
        now = cls._now_ts()
        if isinstance(cache_entry, dict) and "catalog" in cache_entry:
            checked_at = cls._coerce_timestamp(cache_entry.get("checked_at", 0.0))
            status = str(cache_entry.get("status", "success") or "success").strip().lower()
            ttl = (
                int(cls.SOURCE_PDF_CATALOG_POSITIVE_TTL_SECONDS)
                if status == "success"
                else int(cls.SOURCE_PDF_CATALOG_NEGATIVE_TTL_SECONDS)
            )
            if checked_at > 0.0 and (now - checked_at) <= max(5, ttl):
                cached_catalog = cache_entry.get("catalog", {})
                if isinstance(cached_catalog, dict):
                    return dict(cached_catalog)
            cls._source_pdf_catalog_cache.pop(cache_key, None)
        elif isinstance(cache_entry, dict):
            # Backward compatibility for earlier in-memory cache format.
            legacy_catalog = dict(cache_entry)
            cls._source_pdf_catalog_cache[cache_key] = {
                "catalog": legacy_catalog,
                "checked_at": now,
                "status": "success" if legacy_catalog else "empty",
            }
            return legacy_catalog

        catalog: Dict[str, str] = {}
        if source_name == "gceguide":
            level = SubjectDatabase.get_exam_level(subject_code)
            index_url = cls.SOURCES["gceguide"]["index_urls"].get(level)
            if index_url:
                subject_page = cls._resolve_gceguide_subject_page(index_url, subject_code)
                if subject_page:
                    try:
                        html = cls._http_get_text(subject_page, timeout=cls.REQUEST_TIMEOUT_SECONDS)
                        links = re.findall(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
                        for link in links:
                            url = urljoin(subject_page, link)
                            name = os.path.basename(urlsplit(url).path)
                            if not name:
                                continue
                            catalog[cls._normalize_file_key(name)] = url
                    except Exception:
                        pass
        elif source_name in {"papacambridge", "pastpapersco"}:
            base_url = cls._pastpapersco_upload_bases()[0]
            try:
                html = cls._http_get_text(base_url + "/", timeout=cls.PAPACAMBRIDGE_LISTING_TIMEOUT_SECONDS)
                links = re.findall(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
                for link in links:
                    url = urljoin(base_url + "/", link)
                    name = os.path.basename(urlsplit(url).path)
                    if not name:
                        continue
                    if not cls._normalize_file_key(name).startswith(cls._normalize_file_key(subject_code + "_")):
                        continue
                    catalog[cls._normalize_file_key(name)] = url
            except Exception:
                pass
        elif source_name == "dynamicpapers":
            base_url = cls.SOURCES["dynamicpapers"]["base_url"].rstrip("/")
            search_url = f"{base_url}/?s={subject_code}_"
            try:
                html = cls._http_get_text(search_url, timeout=cls.REQUEST_TIMEOUT_SECONDS)
                links = re.findall(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
                for raw_url in links:
                    url = urljoin(base_url + "/", raw_url)
                    name = os.path.basename(urlsplit(url).path)
                    if not name:
                        continue
                    if not cls._normalize_file_key(name).startswith(cls._normalize_file_key(subject_code + "_")):
                        continue
                    catalog[cls._normalize_file_key(name)] = url
            except Exception:
                pass

        cls._source_pdf_catalog_cache[cache_key] = {
            "catalog": dict(catalog),
            "checked_at": now,
            "status": "success" if catalog else "empty",
        }
        cls._prune_cache_by_size(cls._source_pdf_catalog_cache, 1000)
        return catalog

    @classmethod
    def _extract_specimen_meta_from_filename(cls, filename: str, subject_code: str) -> Optional[Dict[str, str]]:
        text = str(filename or "").strip()
        if not text:
            return None
        lower = cls._normalize_file_key(os.path.basename(text))
        if not lower.startswith(cls._normalize_file_key(subject_code + "_")):
            return None

        if not any(token in lower for token in ("_sp_", "_sm_", "specimen", "_spec_", "_spec")):
            return None

        year_val: Optional[str] = None
        m4 = re.search(r"(?:^|_)(20\d{2})(?:_|\.)", lower)
        if m4:
            year_val = m4.group(1)
        if year_val is None:
            m2 = re.search(r"(?:^|_)(?:y)?(\d{2})(?:_|\.)", lower)
            if m2:
                year_val = str(2000 + int(m2.group(1)))
        if year_val is None:
            return None

        paper_match = re.search(r"_(\d{1,2})(?:\.pdf)?$", lower)
        if not paper_match:
            paper_match = re.search(r"_qp_(\d{1,2})(?:\.pdf)?$", lower)
        if not paper_match:
            paper_match = re.search(r"_ms_(\d{1,2})(?:\.pdf)?$", lower)
        if not paper_match:
            return None

        kind = "SP_MS" if "_sm_" in lower or "_ms_" in lower else "SP_QP"
        return {
            "year": year_val,
            "paper": str(int(paper_match.group(1))),
            "kind": kind,
        }

    @classmethod
    def _format_specimen_result(
        cls,
        subject_code: str,
        year: str,
        component: str,
        filename: str,
        url: str,
        source: str,
        kind: str,
    ) -> Dict:
        doc_type = "QP" if kind == "SP_QP" else "MS"
        doc_name = "Specimen Question Paper" if kind == "SP_QP" else "Specimen Mark Scheme"
        return {
            "subject": SubjectDatabase.get_subject_name(subject_code),
            "subject_code": subject_code,
            "year": str(year),
            "series": "SP",
            "component": str(component),
            "type": doc_type,
            "type_name": doc_name,
            "filename": filename,
            "url": url,
            "downloaded": False,
            "source": source,
            "is_specimen": True,
        }

    @staticmethod
    def _extract_paper_numbers(components: List[str]) -> List[str]:
        papers: set[str] = set()
        for component in components:
            text = str(component or "").strip()
            if not text:
                continue
            digits = "".join(ch for ch in text if ch.isdigit())
            if not digits:
                continue
            papers.add(digits[0])
        return sorted(papers)

    @staticmethod
    def _specimen_candidate_years() -> List[str]:
        now = datetime.now().year % 100
        floor = max(0, now - 15)
        return [f"{yy:02d}" for yy in range(now, floor - 1, -1)]

    @staticmethod
    def _normalize_file_key(value: str) -> str:
        normed = os.path.normcase(str(value or "").strip())
        normed = normed.replace("\\", "/")
        return normed.lower()

    @staticmethod
    def _safe_join_path(*parts: str) -> str:
        path = os.path.join(*(str(p) for p in parts if str(p or "").strip()))
        return path.replace("\\", "/")

    @classmethod
    def _attach_listening_resources_from_direct(cls, group: PaperGroup) -> None:
        if not cls._is_listening_component(group.subject_code, group.component):
            return
        series_letter = series_to_code(str(group.session or "").strip().upper())
        if not series_letter:
            return
        year_text = str(group.year or "").strip()
        year_short = year_text[-2:] if len(year_text) >= 2 else year_text
        if not year_short:
            return

        upload_bases = cls._pastpapersco_upload_bases()
        component_candidates = cls._papacambridge_component_fallbacks(str(group.component))
        resource_specs = [
            ("AU", "sf", "mp3", "AUDIO"),
            ("TN", "tn", "pdf", "TRANSCRIPT"),
        ]
        for kind, token, ext, family in resource_specs:
            if kind in group.resources:
                continue
            for component in component_candidates:
                filename = f"{group.subject_code}_{series_letter}{year_short}_{token}_{component}.{ext}"
                attached = False
                for base_url in upload_bases:
                    direct_url = f"{base_url}/{filename}"
                    success, status = cls._pastpapersco_asset_probe(direct_url)
                    cls._log_event(
                        "source.probe",
                        source="pastpapersco",
                        subject=group.subject_code,
                        series=group.session,
                        year=group.year,
                        doc_type=kind,
                        component=component,
                        status=status,
                        exists=bool(success),
                    )
                    if not success:
                        if status in {403, 404}:
                            break
                        if 200 <= status < 300:
                            break
                        continue

                    cls._pastpapersco_preferred_base = base_url
                    open_url, download_url = cls._resolve_open_download_urls(
                        direct_url=direct_url,
                        viewer_url="",
                        extension=ext,
                    )
                    group.resources[kind] = PaperResource(
                        kind=kind,
                        filename=filename,
                        url=direct_url,
                        source="pastpapersco",
                        direct_url=direct_url,
                        open_url=open_url,
                        download_url=download_url,
                        resource_family=family,
                        resource_token=token,
                        extension=ext,
                    )
                    attached = True
                    break
                if attached:
                    break

    @classmethod
    def _attach_compound_resources_direct_probe(cls, group: PaperGroup) -> None:
        session_letter = series_to_code(str(group.session or "").strip().upper())
        if not session_letter:
            return
        year_text = str(group.year or "").strip()
        year_short = year_text[-2:] if len(year_text) >= 2 else year_text
        if not year_short:
            return

        subject_code = str(group.subject_code or "").strip()
        if not subject_code:
            return

        upload_bases = cls._pastpapersco_upload_bases()
        component_candidates = cls._papacambridge_component_fallbacks(str(group.component))
        if not component_candidates:
            return

        # Try common resource naming patterns that are known to exist across
        # inserts, source files, audio, transcripts, and map attachments.
        resource_specs: List[Tuple[str, str, List[Tuple[str, str]]]] = [
            (
                "IN",
                "INSERT",
                [
                    ("in", "pdf"),
                    ("insert", "pdf"),
                    ("inserts", "pdf"),
                    ("insert_booklet", "pdf"),
                    ("passage", "pdf"),
                    ("passage_booklet", "pdf"),
                    ("resource_booklet", "pdf"),
                    ("rp", "pdf"),
                    ("qr", "pdf"),
                ],
            ),
            ("SF", "SOURCE_FILE", [("sf", "zip"), ("source_file", "zip"), ("source_files", "zip")]),
            ("AU", "AUDIO", [("sf", "mp3"), ("au", "mp3"), ("audio", "mp3")]),
            ("TN", "TRANSCRIPT", [("tn", "pdf"), ("transcript", "pdf")]),
            ("MAP", "MAP", [("map", "pdf"), ("map_insert", "pdf")]),
        ]

        for kind, family, tokens in resource_specs:
            if kind in group.resources:
                continue
            if not cls._resource_allowed_for_subject(group.subject_code, group.component, family):
                continue

            attached = False
            for component in component_candidates:
                if attached:
                    break
                for token, ext in tokens:
                    if attached:
                        break
                    filename = f"{subject_code}_{session_letter}{year_short}_{token}_{component}.{ext}"
                    for base_url in upload_bases:
                        direct_url = f"{base_url}/{filename}"
                        success, status = cls._pastpapersco_asset_probe(direct_url)
                        if not success:
                            if status in {403, 404}:
                                break
                            if 200 <= status < 300:
                                break
                            continue

                        cls._pastpapersco_preferred_base = base_url
                        open_url, download_url = cls._resolve_open_download_urls(
                            direct_url=direct_url,
                            viewer_url="",
                            extension=ext,
                        )
                        group.resources[kind] = PaperResource(
                            kind=kind,
                            filename=filename,
                            url=direct_url,
                            source="pastpapersco",
                            direct_url=direct_url,
                            open_url=open_url,
                            download_url=download_url,
                            resource_family=family,
                            resource_token=token,
                            extension=ext,
                        )
                        attached = True
                        break

    @classmethod
    def _attach_compound_resources(cls, groups: Iterable[PaperGroup]) -> None:
        for group in groups:
            base_doc = group.primary_docs.get("QP") or group.primary_docs.get("SP_QP")
            if not base_doc:
                continue

            # Always try PapaCambridge listing metadata first. Primary QP/MS may come
            # from another source due priority order, but resources (insert/audio/etc.)
            # can still exist on PapaCambridge for the same paper component.
            if str(group.session or "").strip().upper() in {"MJ", "ON", "FM"}:
                refs = cls._papacambridge_docs_for_series(
                    subject_code=group.subject_code,
                    year=group.year,
                    series=group.session,
                )
                if refs:
                    for ref in refs:
                        token = str(ref.doc_token or "").strip().lower()
                        if token in {"qp", "ms", "gt"}:
                            continue
                        if str(ref.component or "").strip() and not cls._papacambridge_components_match(
                            str(group.component),
                            str(ref.component),
                        ):
                            continue

                        ext = os.path.splitext(ref.filename)[1].lower().lstrip(".")
                        family = cls._classify_resource_family(token, ext)
                        if family == "OTHER":
                            filename_lower = str(ref.filename or "").lower()
                            if ("_in_" in filename_lower or "_passage_" in filename_lower) and ext == "pdf":
                                family = "INSERT"
                        if not cls._resource_allowed_for_subject(group.subject_code, group.component, family):
                            continue

                        kind = cls.FAMILY_TO_KIND.get(family)
                        if not kind or kind in group.resources:
                            continue

                        open_url, download_url = cls._resolve_open_download_urls(
                            direct_url=ref.direct_url,
                            viewer_url=ref.viewer_url,
                            extension=ext,
                        )
                        group.resources[kind] = PaperResource(
                            kind=kind,
                            filename=ref.filename,
                            url=ref.direct_url,
                            source="papacambridge",
                            direct_url=ref.direct_url,
                            viewer_url=ref.viewer_url,
                            open_url=open_url,
                            download_url=download_url,
                            resource_family=family,
                            resource_token=token,
                            extension=ext,
                        )

            cls._attach_listening_resources_from_direct(group)
            cls._attach_compound_resources_direct_probe(group)

            base_stem = os.path.splitext(str(base_doc.filename or "").strip())[0]
            if not base_stem:
                base_stem = os.path.splitext(os.path.basename(urlsplit(base_doc.url).path))[0]
            if not base_stem:
                continue

            source_catalog = cls._collect_source_pdf_catalog(base_doc.source, group.subject_code)
            suffix_map = {"IN": "_in", "SF": "_sf"}
            for kind, suffix in suffix_map.items():
                if kind in group.resources:
                    continue

                candidate_filename = f"{base_stem}{suffix}.pdf"
                candidate_key = cls._normalize_file_key(candidate_filename)
                candidate_url = source_catalog.get(candidate_key)
                if not candidate_url:
                    candidate_url = cls._build_compound_candidate_url(base_doc.url, suffix)
                    if not candidate_url or not cls._url_exists(candidate_url):
                        candidate_url = ""
                if not candidate_url:
                    continue

                file_name = os.path.basename(urlsplit(candidate_url).path) or candidate_filename
                ext = os.path.splitext(file_name)[1].lower().lstrip(".")
                family = "INSERT" if kind == "IN" else "SOURCE_FILE"
                if not cls._resource_allowed_for_subject(group.subject_code, group.component, family):
                    continue
                open_url, download_url = cls._resolve_open_download_urls(
                    direct_url=candidate_url,
                    viewer_url="",
                    extension=ext,
                )
                group.resources[kind] = PaperResource(
                    kind=kind,
                    filename=file_name,
                    url=candidate_url,
                    source=base_doc.source,
                    direct_url=candidate_url,
                    open_url=open_url,
                    download_url=download_url,
                    resource_family=family,
                    resource_token=kind.lower(),
                    extension=ext,
                )

    @classmethod
    def _build_compound_candidate_url(cls, base_url: str, suffix: str) -> str:
        raw = str(base_url or "").strip()
        if not raw:
            return ""
        parts = urlsplit(raw)
        base_name = os.path.basename(parts.path)
        stem, _ext = os.path.splitext(base_name)
        if not stem:
            return ""
        new_name = f"{stem}{suffix}.pdf"
        new_path = cls._safe_join_path(os.path.dirname(parts.path), new_name)
        return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))

    @classmethod
    def _resolve_gceguide_subject_page(cls, index_url: str, subject_code: str) -> Optional[str]:
        cache_key = f"{index_url}|{subject_code}"
        cache_entry = cls._gceguide_subject_cache.get(cache_key)
        now = cls._now_ts()
        if isinstance(cache_entry, dict):
            checked_at = cls._coerce_timestamp(cache_entry.get("checked_at", 0.0))
            status = str(cache_entry.get("status", "success") or "success").strip().lower()
            ttl = (
                int(cls.GCEGUIDE_SUBJECT_POSITIVE_TTL_SECONDS)
                if status == "success"
                else int(cls.GCEGUIDE_SUBJECT_NEGATIVE_TTL_SECONDS)
            )
            if checked_at > 0.0 and (now - checked_at) <= max(5, ttl):
                subject_page = cache_entry.get("subject_page")
                return str(subject_page) if isinstance(subject_page, str) and subject_page.strip() else None
            cls._gceguide_subject_cache.pop(cache_key, None)
        elif isinstance(cache_entry, str) or cache_entry is None:
            # Backward-compatibility for legacy cache format.
            subject_page = str(cache_entry).strip() if isinstance(cache_entry, str) else ""
            cls._gceguide_subject_cache[cache_key] = {
                "subject_page": subject_page or None,
                "checked_at": now,
                "status": "success" if subject_page else "empty",
            }
            return subject_page or None

        try:
            html = cls._http_get_text(index_url, timeout=cls.REQUEST_TIMEOUT_SECONDS)
        except Exception:
            cls._gceguide_subject_cache[cache_key] = {
                "subject_page": None,
                "checked_at": now,
                "status": "empty",
            }
            return None

        pattern = re.compile(r'href="([^"]+)"[^>]*>[^<]*\(' + re.escape(subject_code) + r'\)', re.IGNORECASE)
        match = pattern.search(html)
        if match:
            subject_page = urljoin(index_url, match.group(1))
            cls._gceguide_subject_cache[cache_key] = {
                "subject_page": subject_page,
                "checked_at": now,
                "status": "success",
            }
            return subject_page

        cls._gceguide_subject_cache[cache_key] = {
            "subject_page": None,
            "checked_at": now,
            "status": "empty",
        }
        return None

    @classmethod
    def _format_result(
        cls,
        subject_code: str,
        year: str,
        series: str,
        component: str,
        doc_type: str,
        filename: str,
        url: str,
        source: str,
        direct_url: str = "",
        viewer_url: str = "",
        resource_family: str = "",
        resource_token: str = "",
        extension: str = "",
    ) -> Dict:
        normalized_type = str(doc_type or "").strip().upper()
        doc_name = {
            "QP": "Question Paper",
            "P": "Question Paper",
            "MS": "Mark Scheme",
            "ER": "Examiner Report",
            "GT": "Grade Threshold",
            "IN": "Insert",
            "SF": "Source File",
            "AU": "Audio",
            "TN": "Transcript",
            "MAP": "Map",
        }.get(normalized_type, normalized_type)
        full_year = "20" + str(year) if len(str(year)) == 2 else str(year)
        direct = str(direct_url or url or "").strip()
        viewer = str(viewer_url or "").strip()
        ext = str(extension or "").strip().lower().lstrip(".")
        if not ext:
            ext = os.path.splitext(str(filename or ""))[1].lower().lstrip(".")
        if not ext:
            ext = os.path.splitext(urlsplit(direct).path)[1].lower().lstrip(".")
        open_url, download_url = cls._resolve_open_download_urls(direct, viewer, ext)

        return {
            "subject": SubjectDatabase.get_subject_name(subject_code),
            "subject_code": subject_code,
            "year": full_year,
            "series": series,
            "component": str(component),
            "type": normalized_type,
            "type_name": doc_name,
            "filename": filename,
            "url": direct,
            "direct_url": direct,
            "viewer_url": viewer,
            "open_url": open_url,
            "download_url": download_url,
            "resource_family": str(resource_family or ""),
            "resource_token": str(resource_token or ""),
            "extension": ext,
            "downloaded": False,
            "source": source,
            "is_specimen": False,
        }
