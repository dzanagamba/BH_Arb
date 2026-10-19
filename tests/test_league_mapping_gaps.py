"""The 661 league-label pairs the certainty gate was refusing, and the fix.

Every pair in these tables was extracted from the real 5,373-match feed by
``scripts/audit_league_pairs.py``: two fixtures with the same canonical home
team, the same canonical away team and the same kickoff, whose two sides
normalise to different league ids, so ``league_mismatch`` rejected them.

Each table is here for one of two reasons, and both matter:

* :data:`LOCALISED_PAIRS` — the two labels are the same competition written in
  two languages. These must now resolve to one canonical id.
* :data:`DELIBERATELY_UNMAPPED` — the two labels are *not* the same
  competition, or the label itself is ambiguous. These must stay apart. A
  mapping that unblocks a blocked pair is worth one review item; a mapping
  that unblocks one of these is a wrong surebet.

:data:`SPLIT_GROUPS` is the part that protects the promise. Every competition
that is really several groups under one root word (UEFA Nations League A-D,
Primera Federación 1-5, Serie C A-C, ...) has one canonical id per group, and
these tests prove the halves of each family still refuse each other.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine.certainty import CertaintyGate
from engine.matcher import MatchMatcher
from engine.normalizer import TeamNormalizer
from models.schemas import Match

# ---------------------------------------------------------------------------
# Pairs that must now resolve to one competition
# ---------------------------------------------------------------------------

# (left raw label, right raw label, expected shared canonical id)
LOCALISED_PAIRS: list[tuple[str, str, str]] = [
    # -- England: the national league system, one tier per canonical id ------
    ("England 3", "Engleska 3", "league_one"),
    ("England 4", "Engleska 4", "league_two"),
    ("England 4", "Engleska FL 2", "league_two"),
    ("Engleska 5", "England 5 Conference", "england_national_league"),
    ("Engleska 5", "National League", "england_national_league"),
    ("Engleska 5", "Engleska NL Premier", "england_national_league"),
    ("England 6 North", "Engleska 6 Sever", "england_national_league_north"),
    ("England 6 North", "Nacionalna Liga Sjever", "england_national_league_north"),
    ("England 6 North", "Engleska NL Sjever", "england_national_league_north"),
    ("England 6 North", "National League, Sjever", "england_national_league_north"),
    ("England 6 South", "Engleska 6 Jug", "england_national_league_south"),
    ("England 6 South", "Nacionalna Liga Jug", "england_national_league_south"),
    ("England 6 South", "Engleska NL Jug", "england_national_league_south"),
    ("England 6 South", "National League, Jug", "england_national_league_south"),
    ("England FA Trophy", "FA Trophy", "england_fa_trophy"),
    ("England FA Trophy", "Engleska - FA Trofej", "england_fa_trophy"),
    ("England FA Trophy", "Engleski FA Trophy Kup", "england_fa_trophy"),
    ("Challenge Kup", "Skotski Challenge Kup", "scottish_challenge_cup"),
    # -- Wales / Northern Ireland ------------------------------------------
    ("Wales 1", "Wales 1.Liga", "wales_cymru_premier"),
    ("Wales 1", "Cymru Premier", "wales_cymru_premier"),
    ("Wales 2 South", "Cymru Championship South", "wales_cymru_championship_south"),
    ("Wales 2 South", "Wales FAW Championship - Jug", "wales_cymru_championship_south"),
    ("Sj Irska Premier Liga", "Severna Irska 1", "northern_ireland_premier"),
    ("Sj Irska Premier Liga", "Northern Ireland 1", "northern_ireland_premier"),
    ("Sj Irska Championship 1", "Severna Irska 2", "northern_ireland_championship"),
    ("Sj Irska Championship 1", "Northern Ireland 2", "northern_ireland_championship"),
    # -- United States -------------------------------------------------------
    ("S A D  -  M L S", "MLS", "mls"),
    ("S A D  -  U S L", "USL CHAMPIONSHIP", "usl_championship"),
    ("S A D  -  U S L  1", "USL League One", "usl_league_one"),
    ("USL Liga 1", "USL League One", "usl_league_one"),
    # -- Spain ---------------------------------------------------------------
    ("Spain 2", "Spanjolska 2.Liga", "laliga_2"),
    ("Spain 1", "Spanjolska 1.Liga", "la_liga"),
    # -- Italy ---------------------------------------------------------------
    ("Talijanska 1.Liga", "Serie A", "serie_a"),
    ("Talijanska 2.Liga", "Serie B", "serie_b"),
    # -- Portugal / Netherlands / Germany ------------------------------------
    ("Portugalska 1.Liga", "Primeira Liga", "primeira_liga"),
    ("Nizozemska 1.Liga", "Eredivisie", "eredivisie"),
    ("Nizozemska 2.Liga", "Eerste Divisie", "eerste_divisie"),
    ("Tweede Divisie", "Nizozemska 3.Liga", "netherlands_tweede_divisie"),
    ("Tweede Divisie", "Holandija 3", "netherlands_tweede_divisie"),
    ("Nemacka 1", "Germany 1", "bundesliga"),
    ("Njemacka 2.Liga", "2. Bundesliga", "bundesliga_2"),
    ("Regionalliga Sjever", "Nemacka 4 Sever", "germany_regionalliga_nord"),
    ("Regionalliga Sjever", "Germany 4 North", "germany_regionalliga_nord"),
    ("Regionalliga Zapad", "Nemacka 4 Zapad", "germany_regionalliga_west"),
    ("Regionalliga Zapad", "Germany 4 West", "germany_regionalliga_west"),
    ("Regionalliga Sjeveroistok", "Nemacka 4 Severoistok", "germany_regionalliga_nordost"),
    # -- France --------------------------------------------------------------
    ("France 1", "Ligue 1", "ligue_1"),
    ("Ligue 2", "Francuska 2.Liga", "france_ligue_2"),
    ("Francuska 3", "France 3", "france_championnat_national"),
    ("Francuska 3", "Francuska 3.Liga", "france_championnat_national"),
    ("France 3", "Francuska 3.Liga", "france_championnat_national"),
    # -- Nordic --------------------------------------------------------------
    ("Svedska 1.Liga", "SWEDEN 1", "allsvenskan"),
    ("Svedska 2.Liga", "Svedska 2", "superettan"),
    ("Sweden 3 North", "Svedska 3 Sever", "sweden_division_1_north"),
    ("Sweden 3 North", "Svedska 3.Liga Sjever", "sweden_division_1_north"),
    ("Sweden 3 North", "Divizija 1. Norra", "sweden_division_1_north"),
    ("Sweden 3 South", "Svedska 3 Jug", "sweden_division_1_south"),
    ("Sweden 3 South", "Svedska 3.Liga Jug", "sweden_division_1_south"),
    ("Sweden 3 South", "Divizija 1. Sorda", "sweden_division_1_south"),
    (
        "Svedska 4.Liga Sodra Gotaland",
        "Svedska 4 Juzni Gotaland",
        "sweden_division_2_sodra_gotaland",
    ),
    ("Norway 3 - Group 1", "Norveska 3 Grupa 1", "norway_3_division_group_1"),
    ("Norway 3 - Group 1", "2. Divizija Grupa 1", "norway_3_division_group_1"),
    ("Norway 3 - Group 1", "Norveska 3.Liga Grupa 1", "norway_3_division_group_1"),
    ("Norway 3 - Group 1", "Norveska 3 A", "norway_3_division_group_1"),
    ("Norway 3 - Group 2", "Norveska 3 Grupa 2", "norway_3_division_group_2"),
    ("Norway 3 - Group 2", "2. Divizija Grupa 2", "norway_3_division_group_2"),
    ("Norway 3 - Group 2", "Norveska 3.Liga Grupa 2", "norway_3_division_group_2"),
    ("Norway 3 - Group 2", "Norveska 3 B", "norway_3_division_group_2"),
    ("Norveska 3 A", "Norveska 3 Grupa 1", "norway_3_division_group_1"),
    ("Norveska 3 B", "Norveska 3 Grupa 2", "norway_3_division_group_2"),
    (
        "Norway 4 - Group 1",
        "Norveska 4.Liga - Grupa 1",
        "norway_4_division_group_1",
    ),
    ("Norway 4 - Group 1", "Norveska 4 - Grupa 1", "norway_4_division_group_1"),
    # -- Denmark / Finland ---------------------------------------------------
    ("Danska 4.Liga", "Danska 4", "danish_3rd_div"),
    ("Ykkosiliga", "Ykkosliiga", "finland_2nd_div"),
    ("Ykkosiliga", "Finska 2", "finland_2nd_div"),
    ("Ykkosliiga", "Finska 2.LIGA", "finland_2nd_div"),
    ("Finska 2.LIGA", "Finska 2", "finland_2nd_div"),
    # -- Austria / Switzerland / Greece / Japan / China / Russia --------------
    ("Austrijska 1.Liga", "Austrija 1", "austrian_bundesliga"),
    ("Austrijska 2.Liga", "Austrija 2", "austrian_2_liga"),
    ("Austria 3 West", "Austrija 3 Zapad", "austria_regionalliga_west"),
    ("Regionalna Liga Zapad", "Austria 3 West", "austria_regionalliga_west"),
    ("Svajcarska 3", "Switzerland 3", "swiss_1_liga"),
    ("Svajcarska 3", "Svicarska 3.Liga", "swiss_1_liga"),
    ("Greece 2", "Grčka 2.Liga", "greece_superleague_2"),
    ("JAPAN 2", "JAPANSKA 2.LIGA", "j_league_2"),
    ("Japan 2", "JAPANSKA 2.LIGA", "j_league_2"),
    ("Japan 3", "JAPANSKA 3.LIGA", "j_league_3"),
    ("Japan 4", "Japan Football League", "j_fl"),
    ("China 2", "KINA 2", "chinese_champions_league"),
    ("Rusija 2", "FNL", "russian_first_league"),
    ("Rusija 2", "Russia 2", "russian_first_league"),
    ("FNL", "Russia 2", "russian_first_league"),
    # -- Balkans -------------------------------------------------------------
    ("Croatia 2", "Hrvatska 2", "croatian_prva_nl"),
    ("Croatia 2", "Hrvatska 2.Liga", "croatian_prva_nl"),
    ("Prva NL", "Hrvatska 2.Liga", "croatian_prva_nl"),
    ("2. SNL", "Slovenija 2", "slovenian_second_league"),
    ("2. SNL", "Slovenia 2", "slovenian_second_league"),
    ("Slovenija 2", "Slovenia 2", "slovenian_second_league"),
    ("Slovačka 2", "Slovakia 2", "slovak_second_league"),
    ("Slovakia 2", "SLOVAČKA  2", "slovak_second_league"),
    # -- Latin America -------------------------------------------------------
    ("Chile 2", "Cileanska 2.Liga", "chile_primera_b"),
    ("Kolumbija 2", "Colombia 2", "colombia_second_division"),
    ("Kolumbija 2", "Kolumbijska 2.Liga", "colombia_second_division"),
    ("Colombia 2", "Kolumbijska 2.Liga", "colombia_second_division"),
    ("Kolumbija 1 - Klausura", "Kolumbijska 1.Liga", "liga_betplay"),
    ("Kolumbija 1 - Klausura", "Primera A", "liga_betplay"),
    ("Kolumbijska 1.Liga", "Primera A, Apertura", "liga_betplay"),
    ("Uruguay 1", "Urugvaj 1 - Klausura", "uruguay_primera"),
    ("Uruguay 1", "Urugvajska 1.Liga", "uruguay_primera"),
    ("Urugvaj 1 - Klausura", "Urugvajska 1.Liga", "uruguay_primera"),
    ("Uruguay 1", "URUGUAY 1", "uruguay_primera"),
    ("URUGUAY 1", "Urugvajska 1.Liga", "uruguay_primera"),
    ("Uruguay 2", "Urugvajska 2.Liga", "uruguay_second_division"),
    ("Uruguay 2", "URUGVAJ  2", "uruguay_second_division"),
    ("Urugvajska 2.Liga", "URUGVAJ  2", "uruguay_second_division"),
    ("Canada 1", "Kanada 1", "canadian_premier_league"),
    ("Canada 1", "Kanadska Premier Liga", "canadian_premier_league"),
    ("Kanada 1", "Kanadska Premier Liga", "canadian_premier_league"),
    ("Guatemala 1", "Guatemala 1.Liga", "guatemala_liga_nacional"),
    ("Guatemala 1", "Liga Nacional, Apertura", "guatemala_liga_nacional"),
    ("Guatemala 1.Liga", "Liga Nacional, Apertura", "guatemala_liga_nacional"),
    ("Guatemala 1 - Apertura", "Liga Nacional, Apertura", "guatemala_liga_nacional"),
    ("Paraguay 1", "Paragvajska 1.Liga", "paraguay_primera"),
    ("Paraguay 1", "Division de Honor, Apertura", "paraguay_primera"),
    ("Paragvaj 1 - Klausura", "Paragvajska 1.Liga", "paraguay_primera"),
    ("Paragvaj 1 - Klausura", "Division de Honor, Apertura", "paraguay_primera"),
    ("Paraguay 2", "Paragvajska 2.Liga", "paraguay_second_division"),
    ("Peru 2", "Peruanska 2.Liga - Grupa A", "peru_second_division"),
    ("Meksiko 1 - Apertura", "Meksička 1.Liga", "liga_mx"),
    ("Liga MX", "MEXICO 1", "liga_mx"),
    ("Meksiko 2 - Apertura", "Meksička 2.Liga", "mexico_liga_expansion"),
    ("Liga de Expansion MX, Apertura", "Meksička 2.Liga", "mexico_liga_expansion"),
    ("Maroko 1", "Marokanska 1.Liga", "morocco_botola"),
    ("Maroko 1", "Morocco 1", "morocco_botola"),
    ("Botola", "Botola Pro D1", "morocco_botola"),
    ("Botola", "Morocco 1", "morocco_botola"),
    ("Botola Pro D1", "Marokanska 1.Liga", "morocco_botola"),
    ("Maroko 1", "MOROCCO 1", "morocco_botola"),
    ("Morocco 1", "MAROKANSKA 1.LIGA", "morocco_botola"),
    # -- Africa / Asia / cups -------------------------------------------------
    ("Africa Cup of Nations - Qualification", "Afrički Kup Nacija Kval", "afcon_qualification"),
    (
        "Afrički Kup Nacija Kvalifikacije",
        "Kvalifikacije za Afrički Kup Nacija",
        "afcon_qualification",
    ),
    (
        "Africa Cup of Nations - Qualification",
        "Kvalifikacije za Afrički Kup Nacija",
        "afcon_qualification",
    ),
    ("ASEAN Cup", "FIFA ASEAN Kup", "asean_cup"),
    ("Asian Games", "Azijske Igre", "asian_games_football"),
    ("Gulf Kup", "Zalivski Kup", "gulf_cup"),
    ("Gulf Kup", "Arabian Gulf Cup", "gulf_cup"),
    ("Gulf Kup", "Gulf Cup Grupa A", "gulf_cup"),
    ("Gulf Kup", "Gulf Cup Grupa B", "gulf_cup"),
    ("Zalivski Kup", "Arabian Gulf Cup", "gulf_cup"),
    ("Euro U21 - Qualification", "Euro U21 Kval", "euro_u21_qualification"),
    ("Brazil - Copa Santa Catarina", "Copa Santa Catarina", "copa_santa_catarina"),
    ("Argentina Cup", "Copa Argentina", "copa_argentina"),
    ("Argentina Kup", "Copa Argentina", "copa_argentina"),
    ("Argentina Cup", "Argentina Kup", "copa_argentina"),
    ("Argentina Superkup", "Superkup", "argentina_supercopa"),
    (
        "Argentina - Supercopa Internacional",
        "Supercopa Internacional",
        "supercopa_internacional",
    ),
    ("Belgium Cup", "Belgijski Kup", "belgian_cup"),
    ("Belgija - Kup", "Belgium Cup", "belgian_cup"),
    ("Chile Cup", "Čile - Kup", "chile_cup"),
    ("Panama 1", "Panama 1 - Apertura", "panama_liga_panameña"),
    ("Panama 1 - Apertura", "Liga Panamena de Futbol, Apertura", "panama_liga_panameña"),
    ("Panama 1 - Apertura", "Panamska 1.Liga Istok", "panama_liga_panameña"),
    ("Liga Panamena de Futbol, Apertura", "Panamska 1.Liga Istok", "panama_liga_panameña"),
    # -- Women's competitions (the Ž/W marker) --------------------------------
    ("Engleska 1 Ž", "ENGLESKA  1  W", "womens_super_league_england"),
    ("Engleska 1 Ž", "Super Liga (Ž)", "womens_super_league_england"),
    ("Engleska 1 Ž", "Super League (Ž)", "womens_super_league_england"),
    ("Engleska 1 Ž", "Engleska Super Liga (Ž)", "womens_super_league_england"),
    ("NWSL (Ž)", "SAD 1 Ž", "nwsl"),
    ("Norveška 1 Ž", "Toppserien (Ž)", "norwegian_women_eliteserien"),
    ("Norveška 1 Ž", "Norveška 1 W", "norwegian_women_eliteserien"),
    ("Švedska 1 Ž", "ŠVEDSKA  1  W", "swedish_women_allsvenskan"),
    ("Švedska 1 Ž", "Damallsvenskan (Ž)", "swedish_women_allsvenskan"),
    ("Španija 1 Ž", "ŠPANIJA  1  W", "spain_women_liga_f"),
    ("Italija 1 Ž", "Serija A (Ž)", "italy_women_serie_a"),
    ("Italija 1 Ž", "Serie A (Ž)", "italy_women_serie_a"),
    ("Belgija 1 Ž", "BELGIJA  1  W", "belgium_women_first_division"),
    ("Belgija 1 Ž", "Superliga (Ž)", "belgium_women_first_division"),
    ("Holandija 1 Ž", "HOLANDIJA  1  W", "netherlands_women_eredivisie"),
    ("Holandija 1 Ž", "Eredivisie (Ž)", "netherlands_women_eredivisie"),
    ("Liga MX (Ž)", "Meksiko 1 Ž", "mexico_women_liga_mx_f"),
    ("Liga MX (Ž)", "MEKSIKO  1  W  -  APERTURA", "mexico_women_liga_mx_f"),
    ("Colombia 1", "Primera A, Apertura", "liga_betplay"),
    ("Uruguay 1", "Primera Division", "uruguay_primera"),
    ("Uruguay 1", "Primera Divizija", "uruguay_primera"),
    ("Vels 1", "Wales 1", "wales_cymru_premier"),
    ("Vels 1", "Cymru Premier", "wales_cymru_premier"),
    ("Italija 3 Grupa A", "Italy 3 - Group A", "italy_serie_c_a"),
    ("Italija 3 B", "Serija C Grupa B", "italy_serie_c_b"),
    ("Italija 3 C", "Serie C, Grupa C", "italy_serie_c_c"),
    ("Primera RFER Grupa 1", "Spain 3 - Group 1", "spain_primera_federacion_1"),
    ("Gvatemala 1", "Guatemala 1", "guatemala_liga_nacional"),
    ("Gvatemala 1", "Liga Nacional, Apertura", "guatemala_liga_nacional"),
    ("Friendly International", "Međunarodne Prijateljske", "international_friendly"),
    (
        "Friendly International",
        "Prijateljske Utakmice Reprezentacije",
        "international_friendly",
    ),
    ("Romania 1", "Rumunija 1", "romanian_liga_1"),
    ("Superliga (Ž)", "Belgija 1 Ž", "belgium_women_first_division"),
]

# ---------------------------------------------------------------------------
# Pairs that must keep failing
# ---------------------------------------------------------------------------

# (left raw label, right raw label, why it stays unmapped)
DELIBERATELY_UNMAPPED: list[tuple[str, str, str]] = [
    (
        "Nacionalna Liga",
        "Engleska 5",
        "admiralbet uses 'Nacionalna Liga' for three different competitions in "
        "the same feed: the English National League, the French Championnat "
        "National and the Guatemalan Liga Nacional",
    ),
    (
        "Nacionalna Liga",
        "Francuska 3",
        "same catch-all label as above - it is French here",
    ),
    (
        "Nacionalna Liga",
        "Guatemala 1",
        "same catch-all label as above - it is Guatemalan here",
    ),
    (
        "Nacionalna Liga",
        "National League",
        "'Nacionalna Liga' is a three-competition catch-all; merging it with "
        "the unambiguous English 'National League' would import the French and "
        "Guatemalan fixtures into the English bucket",
    ),
    ("Liga 2", "Algeria 2", "'Liga 2' carries English, Tunisian and Scottish fixtures"),
    ("Liga Two", "Skotska FL 2", "'Liga Two' (wwin) carries English and Scottish League Two"),
    ("Liga One", "Skotska FL 1", "'Liga One' (wwin) carries English and Scottish League One"),
    ("Liga 2", "Engleska 4", "'Liga 2' is the ambiguous label; 'Engleska 4' was mapped instead"),
    ("Premijer Liga", "Wales 1", "'Premijer Liga' (admiralbet) carries Cymru and Canadian fixtures"),
    ("Premijer Liga", "Canada 1", "'Premijer Liga' (admiralbet) carries Cymru and Canadian fixtures"),
    ("2. Liga", "Turska 3", "'2. Liga' (admiralbet/wwin) carries Slovak and Turkish fixtures"),
    ("2. Liga", "Slovakia 2", "'2. Liga' (admiralbet/wwin) carries Slovak and Turkish fixtures"),
    ("2. SNL", "2. Liga", "'2. Liga' is ambiguous; the Slovenian label was mapped to its own id"),
    ("3. Divizija", "Danska 4.Liga", "'3. Divizija' carries Danish, Uruguayan and Paraguayan fixtures"),
    ("2. Divizija", "Danska 3.Liga", "'2. Divizija' carries Danish, Uruguayan, Turkish, Austrian and Slovak fixtures"),
    ("Division 2", "Sweden 4 - North Svealand", "'Division 2' (wwin) carries several Swedish Division 2 groups"),
    ("Ettan", "Divizija 1. Norra", "'Ettan' (wwin) pools both Ettan groups, so it is a superset, not the group"),
    ("Ettan", "Svedska 3 Jug", "'Ettan' (wwin) pools both Ettan groups, so it is a superset, not the group"),
    ("National", "France 3", "'National' is a bare word and also means the English National League"),
    ("Fudbalsko prvenstvo", "Novi Zeland 2", "'Fudbalsko prvenstvo' is a bare 'football championship' word"),
    ("3. Divizija, Grupa 1", "Norveska 4.Liga - Grupa 1", "a Czech-language label on a Norwegian 4th-tier group"),
    (
        "Peruanska 2.Liga - Grupa A",
        "Segunda Division",
        "'Segunda Division' (wwin) carries both the Paraguayan and the Peruvian "
        "second tier, so it belongs to neither",
    ),
    (
        "brazil_serie_a",
        "Serija B",
        "config/league_mappings.json already pools Brazil tiers 1-3 under "
        "brazil_serie_a; mapping the Serbian tier names into that pool would "
        "formalise the conflation instead of fixing it",
    ),
    (
        "brazil_serie_a",
        "Serija C",
        "same pre-existing Brazil tier pool",
    ),
    (
        "brazil_serie_a",
        "Brazil 3 - Play Off",
        "the Serie C promotion play-off, which the pre-existing Brazil pool cannot express",
    ),
    (
        "Primera Federacion",
        "Primera RFEF Grupa 1",
        "'Primera Federacion' (wwin) pools every Primera Federación group, so it is a superset",
    ),
    (
        "Segunda Federacion",
        "Spain 4 - Group 1",
        "'Segunda Federacion' (wwin) pools every Segunda Federación group",
    ),
    (
        "nations_league",
        "UEFA Nations League - League A",
        "the pooled UEFA Nations League label is the union of leagues A-D and "
        "cannot be decomposed without a per-fixture league, so the split ids stay separate",
    ),
    (
        "champions_league",
        "Slovenia Prva Liga",
        "a club that appears in both competitions - the gate is right to refuse",
    ),
    (
        "Championship",
        "Severna Irska 2",
        "the English Championship and the Northern Ireland Championship share "
        "club names; they are different competitions",
    ),
    ("La Liga", "Uruguay Primera", "a club-name collision across two continents - correctly refused"),
    ("Eerste Divisie", "Championship", "a club-name collision - correctly refused"),
    ("Liga MX", "Argentine Primera", "a club-name collision - correctly refused"),
    ("Serie B", "Ekvadorska 2.Liga - Za Prvaka", "Ecuadorian promotion play-off is not Italian Serie B"),
    ("Chile 2", "Argentina 3 B", "a club-name collision between two national pyramids - correctly refused"),
    (
        "Primera Divizija (Ž)",
        "Spanija 1 Ž",
        "'Primera Division' names the Spanish and the Uruguayan top flight alike, "
        "so the women's label cannot be pinned to one of them from the data",
    ),
    (
        "Prijateljske",
        "Engleska 5",
        "'Prijateljske' alone is the bare Bosnian word for friendlies and carries "
        "club fixtures in other feeds; only the labels that say 'national team' "
        "were mapped",
    ),
    (
        "Prijateljske",
        "Friendly International",
        "'Prijateljske' alone is not specific to national teams",
    ),
    (
        "Premier Liga",
        "Premier League",
        "'premier liga' is deliberately kept generic by "
        "engine/normalizer.GENERIC_LEAGUE_RAW because it names the Bosnian league "
        "as well as the English one",
    ),
    (
        "Vels 1",
        "Premijer Liga",
        "'Premijer Liga' (admiralbet) carries Cymru and Canadian fixtures",
    ),
    (
        "Primera Divizija",
        "La Liga",
        "'Primera Division' now resolves to uruguay_primera, where its fixtures are",
    ),
    (
        "Premiership",
        "Northern Ireland 1",
        "wwin's bare 'Premiership' carries the Northern Irish, the Scottish and "
        "the New Zealand top flight in one label",
    ),
    (
        "Premiership",
        "Scottish Premiership",
        "wwin's bare 'Premiership' also carries Scottish fixtures (falkirk, "
        "dundee, hearts, rangers), so it cannot be Northern Ireland's",
    ),
    (
        "Premiership",
        "Novi Zeland 2",
        "wwin's bare 'Premiership' also carries New Zealand fixtures",
    ),
]

# ---------------------------------------------------------------------------
# Every family of groups that was split, and must stay split
# ---------------------------------------------------------------------------

# family -> (canonical ids that must all stay distinct, one raw label per id)
SPLIT_GROUPS: dict[str, list[tuple[str, str]]] = {
    "UEFA Nations League": [
        ("nations_league_a", "UEFA Nations League - League A"),
        ("nations_league_b", "UEFA Nations League - League B"),
        ("nations_league_c", "UEFA Nations League - League C"),
        ("nations_league_d", "UEFA Nations League - League D"),
    ],
    "UEFA Nations League, kladionica sub-groups": [
        ("nations_league_a", "Liga Nacija Liga A - Grupa 1"),
        ("nations_league_b", "Liga Nacija Liga B - Grupa 1"),
        ("nations_league_c", "Liga Nacija Liga C - Grupa 1"),
        ("nations_league_d", "Liga Nacija Liga D - Grupa 1"),
    ],
    "Spain Primera Federacion": [
        ("spain_primera_federacion_1", "Primera RFEF Grupa 1"),
        ("spain_primera_federacion_2", "Primera RFEF Grupa 2"),
    ],
    "Spain Segunda Federacion": [
        ("spain_segunda_federacion_1", "Segunda PFEF Plej Of"),
        ("spain_segunda_federacion_2", "Segunda RFEF Grupa 2"),
        ("spain_segunda_federacion_3", "Segunda RFEF Grupa 3"),
        ("spain_segunda_federacion_4", "Segunda RFEF Grupa 4"),
        ("spain_segunda_federacion_5", "Segunda RFEF Grupa 5"),
    ],
    "Spain Tercera Federacion": [
        ("spain_tercera_federacion_1", "Tercera RFEF, Sk.1"),
        ("spain_tercera_federacion_2", "Tercera RFEF, Sk.2"),
    ],
    "Italy Serie C": [
        ("italy_serie_c_a", "Italy 3 - Group A"),
        ("italy_serie_c_b", "Italy 3 - Group B"),
        ("italy_serie_c_c", "Italy 3 - Group C"),
    ],
    "Sweden Division 1": [
        ("sweden_division_1_north", "Sweden 3 North"),
        ("sweden_division_1_south", "Sweden 3 South"),
    ],
    "Norway 3. Divisjon": [
        ("norway_3_division_group_1", "Norway 3 - Group 1"),
        ("norway_3_division_group_2", "Norway 3 - Group 2"),
    ],
    "Argentina Primera B Nacional": [
        ("argentine_primera_b_nacional", "Argentina 2"),
        ("argentine_primera_b_metropolitana", "Argentina 3 B"),
        ("argentine_primera_c", "Argentina 4 A"),
    ],
}

KICKOFF = datetime(2026, 9, 26, 18, 45, tzinfo=UTC)


@pytest.fixture(scope="module")
def normalizer() -> TeamNormalizer:
    return TeamNormalizer()


@pytest.fixture(scope="module")
def matcher() -> MatchMatcher:
    return MatchMatcher()


def _pair(book_left: str, league_left: str, book_right: str, league_right: str) -> tuple[Match, Match]:
    """Two fixtures with identical teams and kickoff, differing only in league label."""
    return (
        Match(
            bookmaker=book_left,
            home_team="Lech Poznan",
            away_team="Thun",
            league=league_left,
            kickoff=KICKOFF,
            url=f"https://{book_left}.example/lech-thun",
        ),
        Match(
            bookmaker=book_right,
            home_team="Lech Poznan",
            away_team="Thun",
            league=league_right,
            kickoff=KICKOFF,
            url=f"https://{book_right}.example/lech-thun",
        ),
    )


# ---------------------------------------------------------------------------
# Happy path: the mapped pairs now agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    LOCALISED_PAIRS,
    ids=[f"{a} == {b} -> {c}" for a, b, c in LOCALISED_PAIRS],
)
def test_localised_pair_resolves_to_one_canonical_id(
    left: str, right: str, expected: str, normalizer: TeamNormalizer
) -> None:
    left_id = normalizer.normalize_league(left)
    right_id = normalizer.normalize_league(right)
    assert left_id == right_id, f"{left!r} -> {left_id!r} but {right!r} -> {right_id!r}"
    assert left_id == expected


def test_every_localised_pair_clears_the_league_gate_in_the_real_gate(
    matcher: MatchMatcher,
) -> None:
    """Not just the normalizer: the gate's own league identity must accept them."""
    gate = CertaintyGate(league_equivalences=matcher._equivalences)
    for left, right, _expected in LOCALISED_PAIRS:
        left_match, right_match = _pair("mbet", left, "premier_kladionica", right)
        gate.normalize([left_match, right_match])
        assert gate._league_ok(left_match.league_normalized, right_match.league_normalized), (
            f"league gate still refuses {left!r} / {right!r}"
        )


# ---------------------------------------------------------------------------
# The safety half: the pairs we declined must still be refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right", "reason"),
    DELIBERATELY_UNMAPPED,
    ids=[f"{a} != {b}" for a, b, _ in DELIBERATELY_UNMAPPED],
)
def test_deliberately_unmapped_pair_still_differs(
    left: str, right: str, reason: str, normalizer: TeamNormalizer
) -> None:
    assert normalizer.normalize_league(left) != normalizer.normalize_league(right), reason


def test_every_deliberately_unmapped_pair_is_refused_by_the_gate(
    matcher: MatchMatcher,
) -> None:
    """An ambiguous label is never *mapped*, and never vouches for different teams.

    The fixture itself can still settle it: the same two teams at the same
    kickoff are the same match whatever catch-all label one book files them
    under, so that case is accepted with a `league_unmapped_teams_exact`
    evidence note. A different team spelling leaves the league as the only
    signal, and an ambiguous label must then refuse.
    """
    gate = CertaintyGate(league_equivalences=matcher._equivalences)
    for left, right, reason in DELIBERATELY_UNMAPPED:
        left_match, right_match = _pair("mbet", left, "premier_kladionica", right)
        gate.normalize([left_match, right_match])
        assert not gate._league_ok(
            left_match.league_normalized, right_match.league_normalized
        ), f"{left!r} / {right!r} was mapped: {reason}"
        exact = gate.evaluate_pair(left_match, right_match)
        both_mapped = gate._is_mapped_league(left_match.league_normalized) and (
            gate._is_mapped_league(right_match.league_normalized)
        )
        if both_mapped:
            # Two mapped ids that differ are a contradiction, teams or not.
            assert exact.status == "rejected", f"{left!r} / {right!r}: {exact.reasons}"
        else:
            assert exact.status == "verified", f"{left!r} / {right!r}: {exact.reasons}"
            assert any(e.reason == "league_unmapped_teams_exact" for e in exact.evidence)

        other = right_match.model_copy(update={"home_team": "Lech", "home_team_normalized": ""})
        gate.normalize([other])
        result = gate.evaluate_pair(left_match, other)
        assert "league_mismatch" in result.reasons, f"{left!r} / {right!r} slipped through"
        assert result.status == "rejected"


# ---------------------------------------------------------------------------
# Split groups: the halves must still refuse each other
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(SPLIT_GROUPS))
def test_split_group_family_members_get_distinct_ids(
    family: str, normalizer: TeamNormalizer
) -> None:
    resolved = [(expected, normalizer.normalize_league(raw)) for expected, raw in SPLIT_GROUPS[family]]
    ids = [actual for _, actual in resolved]
    assert len(set(ids)) == len(ids), f"{family} collapsed onto {ids}"
    for (expected, raw), actual in zip(resolved, ids, strict=True):
        assert actual == expected, f"{family}: {raw!r} -> {actual!r}, expected {expected!r}"


def test_split_group_halves_still_refuse_each_other(matcher: MatchMatcher) -> None:
    """The promise: same teams, same kickoff, different group -> still rejected."""
    gate = CertaintyGate(league_equivalences=matcher._equivalences)
    for family, members in SPLIT_GROUPS.items():
        for index, (_left_id, left_label) in enumerate(members):
            for _other_id, other_label in members[index + 1:]:
                left_match, right_match = _pair("mbet", left_label, "wwin", other_label)
                gate.normalize([left_match, right_match])
                result = gate.evaluate_pair(left_match, right_match)
                assert "league_mismatch" in result.reasons, (
                    f"{family}: {left_label!r} and {other_label!r} now match - the "
                    f"groups were conflated"
                )
                assert result.status == "rejected", f"{family}: {left_label!r} vs {other_label!r}"


def test_split_group_members_still_match_their_own_localised_form(
    normalizer: TeamNormalizer,
) -> None:
    """Splitting must not break the same group's other languages."""
    for family, members in SPLIT_GROUPS.items():
        for expected, raw in members:
            assert normalizer.normalize_league(raw) == expected, (
                f"{family}: {raw!r} lost its own identity"
            )


# ---------------------------------------------------------------------------
# The rule itself must not have moved
# ---------------------------------------------------------------------------


def test_league_mismatch_is_still_a_hard_reject() -> None:
    from engine.certainty import HARD_REJECT_REASONS

    assert "league_mismatch" in HARD_REJECT_REASONS


def test_a_wrong_cross_league_claim_is_still_rejected(matcher: MatchMatcher) -> None:
    """Two real, different competitions with one shared club name."""
    gate = CertaintyGate(league_equivalences=matcher._equivalences)
    maribor_cl, maribor_u = _pair("mbet", "UEFA Champions League", "mdshop", "Slovenia 1")
    gate.normalize([maribor_cl, maribor_u])
    result = gate.evaluate_pair(maribor_cl, maribor_u)
    assert result.status == "rejected"
    assert "league_mismatch" in result.reasons


def test_no_new_cross_league_equivalences_were_introduced(matcher: MatchMatcher) -> None:
    """Only the pre-existing Europa/Conference pair may merge two ids."""
    assert matcher._equivalences == {("europa_league", "conference_league")}


def test_mapping_a_localised_label_cannot_leak_into_a_generic_bucket(
    normalizer: TeamNormalizer,
) -> None:
    """A country-qualified label must not become a generic root word."""
    for raw, expected in (
        ("Engleska 4", "league_two"),
        ("Engleska 3", "league_one"),
        ("Nizozemska 2.Liga", "eerste_divisie"),
    ):
        assert normalizer.normalize_league(raw) == expected
    # The bare roots stay generic and unqualified on purpose.
    for raw in ("Liga 2", "Liga Two", "2. Liga", "Premijer Liga", "Nacionalna Liga"):
        assert normalizer.normalize_league(raw) == raw.lower()


def test_a_mens_label_cannot_resolve_to_a_womens_competition(
    normalizer: TeamNormalizer,
) -> None:
    """The Ž/W suffix is the only thing separating the two; losing it is a bug.

    ``engine.normalizer._full_clean`` folds "Ž" to "z", so a mapping added for the
    women's competition must not also swallow the men's label that differs only
    by that suffix. wwin's bare 'Superliga' is the Romanian Liga I and is held
    generic by ``GENERIC_LEAGUE_RAW``; only 'Superliga (Ž)' is the Belgian
    women's league.
    """
    assert normalizer.normalize_league("Superliga (Ž)") == "belgium_women_first_division"
    assert normalizer.normalize_league("Superliga") == "superliga"
    assert normalizer.normalize_league("Super Liga (Ž)") == "womens_super_league_england"
    assert normalizer.normalize_league("Super Liga") == "super liga"
    assert normalizer.normalize_league("NWSL (Ž)") == "nwsl"
    assert normalizer.normalize_league("SAD 1") == "mls"
    for womens in (
        "Engleska 1 Ž",
        "NWSL (Ž)",
        "Norveška 1 Ž",
        "Švedska 1 Ž",
        "Španija 1 Ž",
        "Italija 1 Ž",
        "Belgija 1 Ž",
        "Holandija 1 Ž",
        "Liga MX (Ž)",
        "Superliga (Ž)",
        "Damallsvenskan (Ž)",
        "Eredivisie (Ž)",
        "Super Liga (Ž)",
        "Toppserien (Ž)",
    ):
        resolved = normalizer.normalize_league(womens)
        assert "women" in resolved or resolved == "nwsl", (
            f"{womens!r} resolved to {resolved!r}, which is not a women's competition"
        )
