---
id: "Appendix E"
file: Appende
title: "Geographic Area Codes"
revised: "2022-05"
category: appendix
validation_relevance: low
applies_to: [geographic-area-codes, marc-043, geographic-subdivisions, ethnic-groups, names-as-subjects]
heading_types: [all]
subdivisions_governed: []
pattern_headings: []
pattern_category: ""
related: ["H 170", "H 1631", "H 1893", "H 1916.5", "H 2230", "H 1055", "H 928", "H 1023", "H 980", "H 978", "H 1045"]
summary: >
  Guidelines for assigning MARC Geographic Area Codes (GACs, field 043) based on the subject
  headings assigned to a work. Codes are required for 651 headings, headings with $z, and
  headings implying a geographic orientation (ethnic groups, nationalities, named entities,
  events). Covers local entities, regions, multi-country entities, historic jurisdictions,
  parts of regions, ethnic groups, languages, literature, named entities, events, biography,
  and cross-references to sheets with special GAC instructions. No limit on the number of GACs
  since 2010. Not relevant to validating heading strings.
---

# Appendix E Geographic Area Codes

## Validation rules

1. Assign a GAC (043) when any heading is tagged 651 or contains a $z geographic subdivision. (Appendix E sec. 1)
2. Assign GACs for ethnic groups, nationalities, civilizations, topics qualified by ethnic group or nationality, named entities (including corporate bodies), and events. (Appendix E sec. 1)
3. There is no limit on the number of GACs per record (the LC three-code limit was lifted in 2010); when very many would be needed, consider a broader code. (Appendix E sec. 1)
4. For a local place or feature within a country or first-order division, code the country, or the first-order division for Australia, Canada, China, Great Britain, and the United States. (Appendix E sec. 2)
5. For a Russian region with its own code, use it only for the region as a whole; for entities within it, code Russia (Federation) (e.g. Siberia `e-urs`, Irkutsk `e-ru`). (Appendix E sec. 2)
6. Regions, valleys, and watersheds take the code of the associated feature when one exists (e.g. Great Lakes Region -> Great Lakes). (Appendix E sec. 3)
7. Entities spanning several countries (or first-order divisions where those are coded) get a code for each, or for a larger area. (Appendix E sec. 4)
8. Historic jurisdictions are coded by the corresponding modern jurisdictions/areas. (Appendix E sec. 5)
9. Assign no GAC to grammars and language textbooks, histories of linguistic change, headings that only bring out the language of a publication, or belles-lettres texts lacking a geographic heading. (Appendix E sec. 8, 9)
10. Do not assign a GAC to a genealogical work whose only heading is a family name. (Appendix E sec. 12)

## Full text

**BACKGROUND:** MARC Geographic Area Codes (GACs) provide for broad retrieval of cataloging records by geographic areas of interest. Codes exist for countries, regions, some first order political divisions, mountain ranges, bodies of water, etc. GACs are selected on the basis of the headings assigned to the work being cataloged. Codes are required for headings that imply geographic orientation, as well as for those that are explicitly geographical. Codes are entered by catalogers in the 043 field. This instruction sheet provides guidelines for assigning GACs. The complete list of GACs is published in the *MARC Code List for Geographic Areas*.

Note: Until 2010, the Library of Congress assigned a maximum of three GACs to any one bibliographic record. In 2010, that restriction was lifted. There is currently no limit on the number of GACs that may be assigned to a record.

### 1. General rule

Bring out by code the geographic areas that appear or are implied in the headings assigned to the work being cataloged. If a heading is tagged 651 or contains a geographic subdivision (a $z subfield), assign a code. Assign codes for ethnic groups, nationalities, civilizations, topics qualified by ethnic groups or nationalities, individual named entities, including corporate bodies, and events.

Note: Although there is no limit on the number of codes that may be assigned to any individual bibliographic record, if a large number of codes would be required to cover all of the places that the subject headings encompass, consider assigning one or more GACs at a broader level that would include all of the individual places.

| Heading | Code for |
|---|---|
| Japan--Commerce | Japan |
| Education--France | France |
| Country music [UF Country music--United States] | United States |
| African Americans | United States |
| British | Great Britain |
| Civilization, Germanic | Europe |
| University of Illinois | Illinois |
| Biennale di Venezia (Venice, Italy) | Italy |

### 2. Coding for local entities

Assign the appropriate code for the country or the first order political division for a work about a local geographic feature, region, or jurisdiction that is located within a country or first order political division.

| Heading | Code for |
|---|---|
| Rabat (Morocco) | Morocco |
| Bloke Plateau (Slovenia) | Slovenia |
| Children--New York (State)--New York | New York (State) |
| Education--Washington (State)--Seattle | Washington (State) |
| Architecture--Australia--Sydney (N.S.W.) | New South Wales |
| Vladivostok (Russia) | Russia (Federation) |

Note: Separate codes for the first order divisions of the following countries have been provided: Australia, Canada, China, Great Britain, and the United States.

Codes have also been provided for some individual regions within Russia. For any work dealing with one of these Russian regions as a whole, assign the code indicated. For an entity, such as a city, located within one of these regions, assign the code for Russia (Federation) instead. For example, for a work about Siberia as a whole, assign e-urs, but for a work about the city of Irkutsk, located in Siberia, assign e-ru.

### 3. Regions, valleys, watersheds, etc.

For a region, valley, watershed, etc., associated with a particular feature for which a code exists, assign the code for the corresponding feature.

| Heading | Code for |
|---|---|
| Great Lakes Region | Great Lakes |
| Mississippi River Valley | Mississippi River |

### 4. Entities located in several countries

Code for each country or for the larger geographic area if appropriate.

| Heading | Code for |
|---|---|
| Euphrates River | Turkey; Iraq; Syria |
| European Economic Community countries | Europe |

If an entity is located in several first order political divisions, for countries having separate codes for political divisions, apply the above rule at the division level.

| Heading | Code for |
|---|---|
| Yellowstone River | Wyoming; North Dakota; Montana |
| Colorado River | West (U.S.) |

### 5. Historic jurisdictions, empires, kingdoms, etc.

Assign codes that correspond to modern-day jurisdictions or areas.

| Heading | Code for |
|---|---|
| Byzantine Empire | Mediterranean Region |
| Rome | Europe; Africa, North; Middle East |
| Confederate States of America | Southern States |

Note: These examples illustrate coding for the greatest territorial extent of these entities. For works that discuss a jurisdiction during a period when its territory was more limited and for works focusing on a specific location within a historical jurisdiction, assign the appropriate code for the particular place.

### 6. Parts of regions

If a work discusses only part of a large geographic region for which a code exists, code for both the region and the locality if subject headings for both are assigned. Example:

```
Title: Water resource problems and priorities in the Appalachian region counties of North Carolina.
650 0 $a Water-supply $z Appalachian Region.
650 0 $a Water-supply $z North Carolina.

Code for: Appalachian Region; North Carolina
```

If a single code does not exist specifically for the region, code only for the part of the region covered by the work being cataloged.

### 7. Ethnic groups, nationalities, civilizations, etc.

Assign codes for the jurisdictions or areas where they are located. For an individual element in the population, assign a code only for the present locality, not the place of origin, as long as the people are citizens or permanent residents.

| Heading | Code for |
|---|---|
| Ashantis (African people) | Ghana; Togo; Ivory Coast |
| Hopi Indians | Arizona |
| Indians of North America--Alaska | Alaska |
| British | Great Britain |
| Japanese Americans--Ohio | Ohio |
| African Americans | United States |
| Civilization, Germanic | Europe |

**Foreign members of a population.** Assign codes for both the place of origin and current location of peoples who are in an area other than their permanent homeland, including travelers, temporary residents, noncitizens, and foreign students.

| Heading | Code for |
|---|---|
| British--United States | Great Britain; United States |
| African American students--France | United States; France |
| Americans--France [as unnaturalized expatriates] | United States; France |

**Influence of one nation on another.** For the impact of one place on another, code for both.

| Heading | Code for |
|---|---|
| Great Britain--Colonies--America | Great Britain; America |
| Japan--Intellectual life--American influences | Japan; United States |

**Special topics modified by names of ethnic groups or nationalities.** Code for the ethnic group or nationality. If the work is limited to a specific locality, code for the locality only. If it deals with an area outside of the area normally associated with the people, code for both places.

| Heading | Code for |
|---|---|
| Technical assistance, American | United States |
| African American authors | United States |
| Art, English | Great Britain |
| Poets, American--Ohio | Ohio |
| Pottery, Chinese--Canada | China; Canada |

### 8. Language

Code for the location of a language if the work deals with geographic aspects of the language.

| Heading | Code for |
|---|---|
| French language--Dialects [a work on the distribution of the dialects of France] | France |
| French language--Dialects--Belgium | Belgium |
| Hopi language [a distribution study] | Arizona |

Assign no code to grammars, textbooks for learning the language, histories of linguistic changes such as changes in phonology, etc.

Assign no code if the heading assigned is intended to bring out the language of a publication, e.g.,

```
Sermons, German
English poetry
Buddhism--Prayer-books and devotions--English
```

### 9. Literature

Assign no code to the texts of belles lettres or folk literature unless a subject heading that has a geographic element is assigned to the work. Assign GACs, however, to works that discuss particular literatures.

| Heading | Code for |
|---|---|
| American poetry--California | California |
| American poetry--History and criticism | United States |
| United States--History--War of 1812--Fiction | United States |
| Folk poetry, Tamil--Burma | Burma |
| Canadian drama | [no code] |

### 10. Named entities

Code for the location of individual named entities, including corporate bodies (i.e., entities tagged 610 in bibliographic records), buildings and structures, roads, waterways, railroads, monuments, camps, parks, gardens, etc. For government agencies, code for the jurisdictions the agencies serve.

| Heading | Code for |
|---|---|
| University of Illinois | Illinois |
| Folger Shakespeare Library | Washington (D.C.) |
| Library of Congress | Washington (D.C.) |
| American Water Works Association | United States |
| New England Library Association | New England |
| Great Atlantic & Pacific Tea Co. | United States |
| Old Manse (Concord, Mass.) | Massachusetts |
| Brooklyn Bridge (New York, N.Y.) | New York (State) |
| Southern Pacific Railroad | United States |
| Yellowstone National Park | Idaho; Montana; Wyoming |
| United States. Department of Agriculture | United States |
| Baltimore County Public Schools | Maryland |
| Presbyterian Church (U.S.A.) | United States |

### 11. Events, exhibitions, movements, etc.

Assign a code for the location of the occurrence. Do not code for participating countries unless the country is brought out in a heading assigned to the work being cataloged.

| Heading | Code for |
|---|---|
| Dunkirk, Battle of, Dunkerque, France, 1940 | France |
| World War, 1914-1918 | Europe |
| World War, 1939-1945 | [no code] |
| World War, 1939-1945--Germany | Germany |
| Reformation--Germany | Germany |
| Reformation | Europe |
| United States--History--War of 1812 | United States |
| Maryland--History--War of 1812 | Maryland |
| Canadian Grand Prix Race | Canada |
| Expo (International Exhibitions Bureau) (1967 : Montréal, Québec) | Québec (Province) |
| Occitan movement | France |
| United States--History--Revolution, 1775-1783 | United States |

### 12. Biography and genealogy

Assign codes to any work of biography, individual or collective, and to any work of genealogy, to which headings covered by the general rule are assigned.

Do not assign a code to genealogical works to which the only heading assigned is a family name.

### 13. Specific types of material and specific places

Many individual instruction sheets in this manual include information about assigning GACs when cataloging either specific types of material or material about specific places. These instruction sheets are listed below.

**Specific types of material**

- Core level records. See H 170, sec. 4
- Genealogical works. See H 1631, sec. 4
- Microforms. See H 1893, sec. 3
- Jazz; Popular music. See H 1916.5, sec. 2.d.
- Non-music sound recordings; Visual materials. See H 2230, sec. 7

**Specific places**

- Bosnia and Hercegovina; Croatia; Former Yugoslav Republics; Kosovo; North Macedonia; Montenegro; Serbia; Serbia and Montenegro; Slovenia; Yugoslavia. See H 1055, sec. 5
- Congo. See H 928, sec. 5
- Former Soviet Republics; Soviet Union. See H 1023, sec. 6
- Gaza Strip; Golan Heights; Jerusalem; Palestine; West Bank. See H 980, sec. 5
- Hong Kong. See H 978, sec. 5
- Vatican City. See H 1045, sec. 4
