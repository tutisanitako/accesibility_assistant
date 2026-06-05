/**
 * frontend/js/context.js
 * Tracks conversation context for follow-up questions.
 *
 * KEY RULE: only inject _lastEvent when the follow-up is a BARE question
 * (no specific Georgian noun content). If the user names something themselves,
 * never prepend the previous event.
 */

let _lastVenue  = '';
let _lastPlace  = '';
let _lastEvent  = '';
let _lastDate   = '';

// Pure follow-ups — no event name present, just a question word
const _BARE_EVENT_FOLLOWUP = /^(სად\s+(ტარდება|იმართება|არის|გაიმართება)|მითხარი\s+მეტი|დეტალები|შესახებ|რომელ\s+თეატრ)$/i;
const _BARE_DATE_FOLLOWUP  = /^(როდის\s+(ტარდება|იმართება|იქნება|გაიმართება)|სეანსები|გრაფიკი|განრიგი|რა\s+სეანსებია)$/i;
const _BARE_JOURNEY        = /^(წამიყვანე|მიმიყვანე|გამიყვანე|როგორ\s+მივიდე|გზა\s+მანდ)$/i;

// Bare spatial refs — single word/phrase meaning "there"
const _REF_WORDS  = /^(მანდ|იქ|მანდამდე|იქამდე)$/i;

export function update(userText, responseText, queryData) {
    const lower = userText.toLowerCase();

    // Date tracking
    if (/ხვალ|tomorrow|ხვალინდელ/.test(lower))  _lastDate = 'ხვალ';
    else if (/დღეს|today/.test(lower))            _lastDate = 'დღეს';
    else if (/ზეგ/.test(lower))                   _lastDate = 'ზეგ';
    else if (/ამ კვირ|this week/.test(lower))      _lastDate = 'ამ კვირაში';
    const dm = userText.match(/(\d{1,2})\s*(იან|თებ|მარ|აპრ|მაი|ივნ|ივლ|აგვ|სექ|ოქტ|ნოე|დეკ)/);
    if (dm) _lastDate = `${dm[1]} ${dm[2]}`;

    // Venue from API results (most reliable source)
    if (queryData?.results?.length) {
        const first = queryData.results[0];
        if (first.venue && first.venue !== 'N/A') _lastVenue = first.venue;
        if (first.name) _lastEvent = first.name;
    }

    // Venue from response text (fallback)
    if (!_lastVenue) {
        const vm = responseText.match(/([ა-ჿ\s]{4,}(?:თეატრ\w*|42|სივრც\w*|მუზეუმ\w*))/i);
        if (vm) _lastVenue = vm[1].trim();
    }

    // Place from journey response
    const pm = responseText.match(/^([ა-ჿ\s]{3,20})(?:ში|ამდე|თან)\s+მისასვლელ/);
    if (pm) _lastPlace = pm[1].trim();
}

export function getLastDate() {
    return _lastDate;
}

/**
 * Returns true if the text contains a specific Georgian noun phrase —
 * i.e. the user is asking about something concrete, not doing a bare follow-up.
 */
function _hasSpecificContent(text) {
    const words = text.trim().split(/\s+/);
    // Count "content words" — Georgian words 4+ chars that are not pure question words
    const QUESTION_STEMS = new Set([
        'როდის','სად','როგორ','რომელ','რამდენ','ხანში','ტარდება',
        'იმართება','იქნება','გაიმართება','არის','ვარ','მითხარი',
        'შეგიძლია','გამიყვანე','წამიყვანე','მიმიყვანე','მივიდე',
        'ჩავიდე','წავიდე','გამიყვანე','გამოდი','გამოდის',
    ]);
    const contentWords = words.filter(w => {
        const wl = w.replace(/[^ა-ჿ]/g, '');
        return wl.length >= 4 && !QUESTION_STEMS.has(w.toLowerCase());
    });
    return contentWords.length >= 1;
}

export function enrich(text, savedHome) {
    const lower   = text.toLowerCase();
    const trimmed = text.trim();

    // "from X to home" — replace home word with saved address
    if (savedHome?.address) {
        const toHomePatterns = [/სახლამდე/, /სახლში\s+მივი/, /სახლისკენ/];
        if (toHomePatterns.some(p => p.test(lower)) && /იდან|მეტრო|სადგურ|გაჩერება/.test(lower)) {
            return text.replace(
                /სახლამდე|სახლში\s+მივი\w*|სახლისკენ/g,
                savedHome.address + '-ამდე',
            );
        }
    }

    // Bare spatial reference ("მანდ", "იქ") → inject last venue
    if (_REF_WORDS.test(trimmed) && (_lastVenue || _lastPlace || _lastEvent)) {
        const ctx = _lastVenue || _lastPlace || _lastEvent;
        return `${text} (${ctx})`;
    }

    // Pure follow-up about event (NO named content) → prepend last event
    if (_BARE_EVENT_FOLLOWUP.test(trimmed) && _lastEvent && !_hasSpecificContent(trimmed)) {
        return `${_lastEvent} ${text}`;
    }
    if (_BARE_DATE_FOLLOWUP.test(trimmed) && _lastEvent && !_hasSpecificContent(trimmed)) {
        return `${_lastEvent} ${text}`;
    }

    // Bare journey phrase with no destination → inject last known place
    if (_BARE_JOURNEY.test(trimmed) && (_lastVenue || _lastPlace || _lastEvent)) {
        const ctx = _lastVenue || _lastPlace || _lastEvent;
        return `${text} ${ctx}`;
    }

    return text;
}

export function reset() {
    _lastVenue = ''; _lastPlace = ''; _lastEvent = ''; _lastDate = '';
}