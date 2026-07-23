"""One-off startup fixups for the JSON-backed store. This is a personal,
single-user app, so a couple of guarded functions here is proportionate --
not a full migration framework."""
from .services.generator import _apply_tag_root, _strip_tag_root
from .storage import store


def run_migrations() -> None:
    _migrate_tag_root()
    _migrate_remove_tag_root()


def _migrate_tag_root() -> None:
    """Retroactively prepend each card's own deck name to its tags, for
    cards created before that was enforced automatically. Superseded by
    _migrate_remove_tag_root below -- kept only so it stays a no-op for any
    install that hasn't run it yet, rather than skipping straight to the
    newer migration and leaving old tags unprefixed-then-never-stripped."""
    if store.is_tag_root_migrated():
        return
    for card in store.list_cards():
        new_tags = _apply_tag_root(card.tags, card.deck)
        if new_tags != card.tags:
            card.tags = new_tags
            store.update_card(card)
    store.mark_tag_root_migrated()


def _migrate_remove_tag_root() -> None:
    """Deck-as-tag-root turned out to be redundant noise when a deck is
    someone's whole broad subject (e.g. every card under 'Anesthesia', so
    the prefix differentiates nothing). New cards no longer get it; this
    retroactively strips it from cards tagged under the old behavior."""
    if store.is_tag_root_removed_migrated():
        return
    for card in store.list_cards():
        new_tags = _strip_tag_root(card.tags, card.deck)
        if new_tags != card.tags:
            card.tags = new_tags
            store.update_card(card)
    store.mark_tag_root_removed_migrated()
