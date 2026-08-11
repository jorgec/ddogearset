import { BrowserOpenURL } from '../../wailsjs/runtime/runtime';

/**
 * A ddowiki search URL that jumps straight to the page when the name matches
 * exactly, and shows results when it does not.
 *
 * `go=Go` is what makes that happen — it is MediaWiki's "Go" button rather than
 * its "Search" button. Without it an exact match still lands on a results page
 * with a single row, which is one extra click on the common case.
 *
 * NOTE: this is the third wiki-URL shape in the codebase, and deliberately not a
 * fourth implementation of one of the others:
 *
 *   - `internal/services/enrichment.go`'s `wikiURLFor` builds
 *     `/page/Special:Search?search=…`, surfaced as an item's `wiki_url`.
 *   - `ItemDetail.svelte`'s `openWiki` builds `/page/Item:Name_With_Underscores`,
 *     a direct page link that 404s when the page name differs from the item
 *     name.
 *
 * ItemDetail's own comment records that keeping those two apart was a
 * deliberate call ("changing link targets silently is not in scope"), so this
 * does not touch them. Worth consolidating on this shape one day — it degrades
 * to a search instead of a 404 — but that is a change to existing behaviour and
 * should be asked for, not slipped in.
 */
export function wikiSearchURL(name: string): string {
    // URLSearchParams gives `+` for spaces and escapes apostrophes as %27,
    // which item names genuinely contain ("Van Richten's Cane").
    const params = new URLSearchParams({
        search: name,
        title: 'Special:Search',
        go: 'Go',
    });
    return `https://ddowiki.com/index.php?${params.toString()}`;
}

/**
 * Open a wiki search in the user's real browser.
 *
 * MUST go through Wails' BrowserOpenURL. A plain `<a href>` navigates the
 * WEBVIEW to ddowiki and there is no way back — the app is simply gone, with no
 * error and no back button. Same family of Wails-specific trap as
 * `window.confirm` silently returning false (see TestFrontendUsesNoNativeDialogs).
 */
export function openWikiSearch(name: string): void {
    if (!name) return;
    BrowserOpenURL(wikiSearchURL(name));
}
