"""One-off startup fixups for the JSON-backed store. This is a personal,
single-user app, so a couple of guarded functions here is proportionate --
not a full migration framework."""
from .services.generator import _apply_tag_root
from .storage import store


def run_migrations() -> None:
    _migrate_tag_root()


def _migrate_tag_root() -> None:
    """Retroactively prepend each card's own deck name to its tags, for
    cards created before that was enforced automatically."""
    if store.is_tag_root_migrated():
        return
    for card in store.list_cards():
        new_tags = _apply_tag_root(card.tags, card.deck)
        if new_tags != card.tags:
            card.tags = new_tags
            store.update_card(card)
    store.mark_tag_root_migrated()
