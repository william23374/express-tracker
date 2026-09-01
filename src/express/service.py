from __future__ import annotations

from datetime import datetime
from typing import Optional

from express.config import (
    CONFIG_PATH,
    AppConfig,
    DEFAULT_PROVIDER_CHAIN,
    load_config,
    save_default_provider,
)
from express.models import Shipment, TrackingEvent, TrackResult
from express.providers.base import (
    ProviderError,
    TrackingProvider,
    available_providers,
    create_provider,
    load_builtin_providers,
)
from express.storage import SQLiteStore, merge_events
from express.validation import (
    is_phone_related_error,
    phone_query_hint,
    validate_tracking_number,
)


class TrackingService:
    def __init__(
        self,
        config: AppConfig | None = None,
        store: SQLiteStore | None = None,
        provider: TrackingProvider | None = None,
    ):
        load_builtin_providers()
        self.config = config or load_config()
        self.store = store or SQLiteStore()
        self.provider = provider or self._build_provider(self.config)

    @staticmethod
    def _chain_candidate(
        config: AppConfig, name: str
    ) -> Optional[TrackingProvider]:
        """Build one provider for the fallback chain; None = skip."""
        if name == "huawei_jm":
            if not config.has_huawei_jm_credentials():
                return None
            return create_provider(
                "huawei_jm",
                app_key=config.huawei_jm_appkey,
                app_secret=config.huawei_jm_appsecret,
            )
        if name == "huawei_kd100":
            if not config.has_kd100_credentials():
                return None
            return create_provider(
                "huawei_kd100",
                app_key=config.kd100_appkey,
                app_secret=config.kd100_appsecret,
            )
        if name == "ali_kd100":
            if not config.has_ali_kd100_credentials():
                return None
            return create_provider(
                "ali_kd100",
                app_code=config.ali_kd100_appcode,
            )
        if name in available_providers():
            # Any registered provider can join the chain.
            return create_provider(name)
        return None

    @staticmethod
    def _build_provider(config: AppConfig) -> TrackingProvider:
        return TrackingService._build_single(config, config.default_provider)

    @staticmethod
    def _build_single(config: AppConfig, name: str) -> TrackingProvider:
        """Build one provider by name; "auto" builds the chain."""
        name = (name or config.default_provider).strip().lower()
        if name in ("auto", "fallback"):
            chain = config.provider_chain or DEFAULT_PROVIDER_CHAIN
            providers: list[TrackingProvider] = []
            for pname in chain:
                candidate = TrackingService._chain_candidate(config, pname)
                if candidate is not None:
                    providers.append(candidate)
            if not providers:
                return create_provider("mock")
            return create_provider("fallback", providers=providers)
        if name == "huawei_jm":
            if not config.has_huawei_jm_credentials():
                return create_provider("mock")
            return create_provider(
                "huawei_jm",
                app_key=config.huawei_jm_appkey,
                app_secret=config.huawei_jm_appsecret,
            )
        if name == "huawei_kd100":
            if not config.has_kd100_credentials():
                return create_provider("mock")
            return create_provider(
                "huawei_kd100",
                app_key=config.kd100_appkey,
                app_secret=config.kd100_appsecret,
            )
        if name == "ali_kd100":
            if not config.has_ali_kd100_credentials():
                return create_provider("mock")
            return create_provider(
                "ali_kd100",
                app_code=config.ali_kd100_appcode,
            )
        if name in available_providers():
            return create_provider(name)
        raise ProviderError(
            f"Unknown provider '{name}'. Available: {', '.join(available_providers())} or 'auto'"
        )

    def switch_provider(self, name: str) -> str:
        """Switch the active provider at runtime and persist it to config."""
        name = name.strip().lower()
        if name not in ("auto", "fallback") and name not in available_providers():
            raise ProviderError(
                f"Unknown provider '{name}'. Available: {', '.join(available_providers())} or 'auto'"
            )
        # Guard cred-requiring providers so the user isn't silently switched to mock
        if name == "huawei_jm" and not self.config.has_huawei_jm_credentials():
            raise ProviderError(
                "Provider 'huawei_jm' needs AppKey + AppSecret. "
                f"Configure [huawei_jm] in {CONFIG_PATH}, or use 'auto'."
            )
        if name == "huawei_kd100" and not self.config.has_kd100_credentials():
            raise ProviderError(
                "Provider 'huawei_kd100' needs AppKey + AppSecret. "
                f"Configure [huawei_kd100] in {CONFIG_PATH}, or use 'auto'."
            )
        if name == "ali_kd100" and not self.config.has_ali_kd100_credentials():
            raise ProviderError(
                "Provider 'ali_kd100' needs an Aliyun Cloud Marketplace AppCode. "
                f"Configure [ali_kd100] in {CONFIG_PATH}, or use 'auto'."
            )
        self.provider = self._build_single(self.config, name)
        self.config.default_provider = name
        try:
            save_default_provider(name)
        except OSError as exc:
            raise ProviderError(
                f"switched in-session, but could not persist config: {exc}"
            ) from exc
        return name if name in ("auto", "fallback") else getattr(self.provider, "name", name)

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", self.config.default_provider)

    def add(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        note: str = "",
        phone: str = "",
        detect: bool = True,
        *,
        track: bool = True,
    ) -> Shipment:
        tracking_number = validate_tracking_number(tracking_number)
        company_code = (company or "").strip().lower()
        company_name = ""
        # Keep the FULL phone so the active provider can decide how much to
        # send (HuaweiCloud needs the whole number for ZTO/SF; others only
        # the last-4). Providers handle the per-courier choice themselves.
        stored_phone = phone.strip()

        if detect and not company_code:
            hints = self.provider.detect_company(tracking_number)
            if hints:
                company_code = hints[0].code
                company_name = hints[0].name
            else:
                raise ProviderError(
                    f"Cannot detect courier for {tracking_number}. "
                    "Pass C<code> (sf yt zto sto yd jtexpress jd ems ...)"
                )

        existing = self.store.get_by_number(tracking_number)
        effective_phone = stored_phone or (existing.phone if existing else "")
        if existing:
            updated = self.store.update_meta(
                existing.id,
                company_code=company_code or None,
                company_name=company_name or None,
                note=note or None,
                phone=stored_phone or None,
            )
            shipment = updated or existing
        else:
            shipment = self.store.add(
                tracking_number=tracking_number,
                company_code=company_code,
                company_name=company_name,
                note=note,
                phone=stored_phone,
            )

        if track and self.provider_name != "mock":
            try:
                self.track_number(
                    tracking_number=shipment.tracking_number,
                    company=shipment.company_code or None,
                    phone=shipment.phone or effective_phone or None,
                    persist=shipment,
                    validate=False,
                )
                refreshed = self.store.get_by_id(shipment.id)
                if refreshed:
                    shipment = refreshed
            except ProviderError as exc:
                # Keep saved shipment; live query may fail (privacy number / quota)
                if is_phone_related_error(str(exc)):
                    shipment._track_warning = (  # type: ignore[attr-defined]
                        "courier rejected phone last-4 (often ecommerce privacy number). "
                        "Shipment saved; live track unavailable via API."
                    )
                else:
                    shipment._track_warning = str(exc)  # type: ignore[attr-defined]

        return shipment

    def list(self) -> list[Shipment]:
        return self.store.list()

    def remove(self, ref: str) -> bool:
        return self.store.delete(ref)

    def resolve(self, ref: str) -> Optional[Shipment]:
        return self.store.resolve(ref)

    def edit(
        self,
        ref: str,
        *,
        tracking_number: Optional[str] = None,
        company: Optional[str] = None,
        note: Optional[str] = None,
        phone: Optional[str] = None,
        clear_phone: bool = False,
        clear_note: bool = False,
    ) -> Shipment:
        """Update saved shipment metadata (does not call the tracking API)."""
        shipment = self.store.resolve(ref)
        if not shipment:
            raise ProviderError(
                f"Shipment not found: {ref}. Use LIST to see saved IDs."
            )

        new_number: Optional[str] = None
        if tracking_number is not None:
            new_number = validate_tracking_number(tracking_number)

        company_code: Optional[str] = None
        company_name: Optional[str] = None
        if company is not None:
            company_code = company.strip().lower()
            company_name = company_code

        phone_value: Optional[str] = None
        if phone is not None:
            phone_value = phone.strip()

        if (
            tracking_number is None
            and company is None
            and note is None
            and phone is None
            and not clear_phone
            and not clear_note
        ):
            raise ProviderError(
                r"usage: MODIFY:NUMBER\[/C]\[/P]\[/N]\[/T]"
            )

        updated = self.store.update_fields(
            shipment.id,
            tracking_number=new_number,
            company_code=company_code,
            company_name=company_name,
            note=note,
            phone=phone_value,
            clear_phone=clear_phone,
            clear_note=clear_note,
        )
        if not updated:
            raise ProviderError(f"Failed to update: {ref}")
        return updated

    def track_number(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
        persist: Optional[Shipment] = None,
        *,
        validate: bool = True,
    ) -> TrackResult:
        if validate:
            tracking_number = validate_tracking_number(tracking_number)
        else:
            tracking_number = tracking_number.strip()
        result = self.provider.track(
            tracking_number=tracking_number,
            company=company,
            phone=phone,
        )
        if persist:
            location = ""
            event_time = None
            if result.current:
                location = result.current.location or result.current.description
                event_time = result.current.time
            self.store.update_meta(
                persist.id,
                company_code=result.company_code or persist.company_code,
                company_name=result.company_name or persist.company_name,
                last_status=result.status,
                last_location=location,
                last_event_time=event_time,
            )
            # Accumulate the tracking history locally so `history` stays stable
            # even when a provider returns only the latest event.
            stored = self.store.get_events(persist.id)
            merged = merge_events(stored, result.events)
            self.store.save_events(persist.id, merged)
            result.events = merged
        return result

    def get(self, ref: str) -> TrackResult:
        shipment = self.store.resolve(ref)
        if not shipment:
            raise ProviderError(
                f"Shipment not found: {ref}. "
                "Use LIST, or QUERY:NUMBER for a one-off lookup."
            )
        try:
            return self.track_number(
                tracking_number=shipment.tracking_number,
                company=shipment.company_code or None,
                phone=shipment.phone or None,
                persist=shipment,
                validate=False,  # already stored
            )
        except ProviderError as exc:
            msg = str(exc)
            # Rate limit / quota: show last cached snapshot if we have one
            if shipment.last_status or shipment.last_location:
                if any(
                    k in msg
                    for k in (
                        "429",
                        "rate limit",
                        "quota",
                        "4030",
                        "112",
                        "额度",
                        "次数不足",
                        "次数已用完",
                        "今日免费额度",
                    )
                ):
                    return self._cached_result(shipment, note=msg)
            raise

    @staticmethod
    def _cached_result(shipment: Shipment, *, note: str = "") -> TrackResult:
        from express.status import extract_location

        loc = extract_location(shipment.last_location, "") or shipment.last_location
        desc = shipment.last_location or shipment.last_status or "(cached)"
        if note:
            desc = f"{desc}  [cached — {note}]"
        ev = TrackingEvent(
            time=shipment.last_event_time or shipment.updated_at or datetime.now(),
            description=desc,
            location=loc,
            status=shipment.last_status,
        )
        events = shipment.events or [ev]
        return TrackResult(
            tracking_number=shipment.tracking_number,
            company_code=shipment.company_code,
            company_name=shipment.company_name or shipment.company_code,
            status=shipment.last_status or "Unknown",
            status_code="cached",
            current=ev,
            events=events,
            raw={"cached": True, "warning": note},
        )

    def hist(self, ref: str) -> TrackResult:
        return self.get(ref)

    def query(
        self,
        tracking_number: str,
        company: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> TrackResult:
        # Prefer saved shipment (id or number) so stored phone/company apply
        saved = self.store.resolve(tracking_number.strip())
        if saved:
            return self.track_number(
                tracking_number=saved.tracking_number,
                company=company or saved.company_code or None,
                phone=phone or saved.phone or None,
                persist=saved,
                validate=False,
            )
        return self.track_number(
            tracking_number=tracking_number,
            company=company,
            phone=phone,
            persist=None,
            validate=True,
        )

    def record_lookup(
        self,
        tracking_number: str,
        company: Optional[str],
        phone: Optional[str],
        result: TrackResult,
    ) -> Optional[Shipment]:
        """Persist a one-off TRACK result so it shows up in LIST / HIST.

        Called after a successful lookup of a not-yet-saved number. Uses the
        explicit C tag or the provider-identified courier, and stores the given
        phone (full number / last-4) as provided.
        """
        tracking_number = validate_tracking_number(tracking_number)
        company_code = (company or result.company_code or "").strip().lower() or None
        if not company_code:
            return None  # courier unknown yet; skip persisting

        existing = self.store.get_by_number(tracking_number)
        if existing:
            shipment = self.store.update_meta(
                existing.id,
                company_code=company_code,
                company_name=result.company_name or company_code,
                phone=(phone or existing.phone) or None,
            )
        else:
            shipment = self.store.add(
                tracking_number=tracking_number,
                company_code=company_code,
                company_name=result.company_name or company_code,
                note="",
                phone=phone or "",
            )

        location = ""
        event_time = None
        if result.current:
            location = result.current.location or result.current.description
            event_time = result.current.time
        if shipment:
            shipment = self.store.update_meta(
                shipment.id,
                company_code=company_code,
                company_name=result.company_name or company_code,
                last_status=result.status,
                last_location=location,
                last_event_time=event_time,
            )
            merged = merge_events(self.store.get_events(shipment.id), result.events)
            self.store.save_events(shipment.id, merged)
        return shipment
