"""One-off startup fixups for the JSON-backed store. This is a personal,
single-user app, so a couple of guarded functions here is proportionate --
not a full migration framework."""
from .services.generator import _apply_tag_root, _strip_tag_root
from .storage import store


def run_migrations() -> None:
    _migrate_tag_root()
    _migrate_remove_tag_root()
    _migrate_readd_tag_root()


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


def _migrate_remove_tag_root() -> None:
    """Briefly removed: deck-as-tag-root seemed redundant when a deck is
    someone's whole broad subject. Reverted by _migrate_readd_tag_root
    below -- kept only so this stays a no-op on installs that already ran
    it, rather than re-stripping tags out from under the next migration."""
    if store.is_tag_root_removed_migrated():
        return
    for card in store.list_cards():
        new_tags = _strip_tag_root(card.tags, card.deck)
        if new_tags != card.tags:
            card.tags = new_tags
            store.update_card(card)
    store.mark_tag_root_removed_migrated()


def _migrate_readd_tag_root() -> None:
    """Restores deck-as-tag-root after _migrate_remove_tag_root turned out
    to be the wrong call -- runs under its own flag since
    is_tag_root_migrated() is already set from the original migration and
    won't fire again on its own."""
    if store.is_tag_root_readded_migrated():
        return
    for card in store.list_cards():
        new_tags = _apply_tag_root(card.tags, card.deck)
        if new_tags != card.tags:
            card.tags = new_tags
            store.update_card(card)
    store.mark_tag_root_readded_migrated()
