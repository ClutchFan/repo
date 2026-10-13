import os, pathlib
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    openai_api_key: str
    sec_user_agent: str
    cache_path: pathlib.Path
    profile_path: pathlib.Path
    model: str

    @classmethod
    def from_env(cls, env, sec_contact=None, base_dir=None):
        base_dir = pathlib.Path(base_dir or os.getcwd())
        if not sec_contact:
            raise ValueError("SEC contact name and email are required")
        name, email = sec_contact
        key = env.get("OPENAI_API_KEY", "")
        return cls(
            openai_api_key=key,
            sec_user_agent=f"{name} {email}",
            cache_path=base_dir / "cache" / "http.sqlite",
            profile_path=pathlib.Path.home() / ".finagent" / "profile.json",
            model=env.get("FINAGENT_MODEL", "gpt-4o"),
        )
