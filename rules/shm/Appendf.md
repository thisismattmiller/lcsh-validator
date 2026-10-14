---
id: "Appendix F"
file: Appendf
title: "Subject-Related Codes in Field 008 - Books"
revised: "2013-06"
category: appendix
validation_relevance: low
applies_to: [marc-008, fixed-field-coding, biography, form-subdivisions]
heading_types: [all]
subdivisions_governed: ["--Congresses"]
pattern_headings: []
pattern_category: ""
related: ["H 1690", "Appendix G"]
summary: >
  LC guidelines for coding subject-related 008 elements in MARC 21 book records: 008/22 target
  audience (j or blank only), 008/24-27 nature of contents (up to four codes, driven by form
  subdivisions and content), 008/29 conference publication (1 when --Congresses is a form
  subdivision), 008/33 literary form (1 only for prose fiction classed in P), and 008/34
  biography codes a, b, c, d with criteria for what counts as biographical. Not relevant to
  heading-string validation except as a consistency check with --Congresses.
---

# Appendix F Subject-Related Codes in Field 008 - Books

## Validation rules

1. [LC practice] 008/22 (Target audience): code `j` if the work is juvenile per H 1690, otherwise blank; no other codes. (Appendix F sec. 1)
2. [LC practice] 008/24-27 (Nature of contents): code each type of material that corresponds to a form subdivision assigned in a subject heading, or that forms a significant part of the work; up to four codes. (Appendix F sec. 2)
3. [LC practice] 008/29 (Conference publication): code `1` if `--Congresses` is used as a form subdivision ($v) in any 6XX field; otherwise `0`. (Appendix F sec. 3)
4. [LC practice] 008/33 (Literary form): code `1` only for prose fiction classed in P; not for drama, poetry, folklore classed in G, or mythology classed in B; otherwise `0`. (Appendix F sec. 4)
5. [LC practice] 008/34 (Biography): `a` individual autobiography, `b` individual biography, `c` collective biography/autobiography, `d` contains biographical information; blank if none. (Appendix F sec. 5.a, 5.b)
6. [LC practice] Do not code biography for portrait collections without biographical description, genealogies without biographical information, literary criticism without biographical information, biography of animals, or fictionalized biography. (Appendix F sec. 5.c)
7. [LC practice] Works on a ruler's reign, or on a doctrine/movement's intellectual content, are not coded as biography unless the personal life gets considerable attention. (Appendix F sec. 5.d)

## Full text

**BACKGROUND:** Several data elements in the 008 field are directly related to the subject matter of the item being cataloged or to the type of information it contains. In MARC 21 book records, these elements are 008/22 (Target audience); 008/24-27 (Nature of contents); 008/29 (Conference publication); 008/33 (Literary form); and 008/34 (Biography). This instruction sheet provides guidelines followed by Library of Congress catalogers in coding these elements of the 008 field. It replaces D 145, an instruction sheet that was formerly in the *Subject Cataloging Manual: General Cataloging Procedures*. The terminology used in these instructions corresponds to that used in the LC ILS (Voyager), the system used by Library of Congress catalogers to create and edit book records.

### 1. 008/22 (Target audience)

If the work is juvenile, as described in H 1690, select the code j: Juvenile. Otherwise, accept the default setting _: Unknown or not specified. Do not select any code other than j or _.

### 2. 008/24-27 (Nature of contents)

#### a. General principle

To any work that is assigned a subject heading with a form subdivision for which there a corresponding Nature of contents code, select that code. Also select a code if a work contains a significant amount of the type of material represented by the code, even if it is not brought out in the subject headings assigned.

#### b. Number of codes

Assign as many as four codes (one each in field 008/24, 008/25, 008/26, and 008/27) to any work that contains more than one type of material. If no code is being specified for any one or more of these data elements, accept the default setting _: No (or, no additional) specified nature of contents.

#### c. Codes and definitions

A full list of the available codes, together with definitions and application guidelines, is in the *MARC 21 Format for Bibliographic Data*, accessible via Cataloger's Desktop or on the Web at <http://www.loc.gov/marc/bibliographic/bd008b.html>

### 3. 008/29 (Conference publication)

If --Congresses is used as a form subdivision in the 6XX fields, select the code 1: Conference publication. Otherwise, accept the default setting 0: Not a conference publication.

### 4. 008/33 (Literary form)

If the work is fiction, select the code 1: Fiction (not further specified). Select this code only for prose fiction classed in P in the LC classification. Do not use the code for drama, poetry, folklore material classed in G, or mythology classed in B. If the work is not fiction, accept the default setting 0: Not fiction (not further specified). Do not select any code other than 0 or 1.

### 5. 008/34 (Biography)

#### a. Valid biography codes

The following codes are valid for field 008/34:

| Code | Meaning |
|---|---|
| a | individual autobiography, including works that are both autobiographical and biographical (e.g. My life with [a famous person]) |
| b | individual biography |
| c | collective biography or autobiography, i.e. works that contain two or more biographies |
| d | contains biographical information (individual or collective) |

#### b. Guidelines for assigning a biography code

If a work is entirely or mostly biographical, select code a, b, or c in field 008/34, as appropriate. If the work has biographical information that is judged to be significant, but is insufficient for coding a, b, or c, enter code d. If the work contains no biographical material, accept the default setting _: No biographical material. Consider the following types of material to be biographical:

- Straightforward accounts of a person's life, character, thought, and activities.
- Accounts of limited periods or aspects of a person's life, e.g. Goethe as a government official.
- Collections of documents relating to a person's life, such as birth, marriage, or death certificates, commissions, diplomas, etc.
- Obituaries, funeral orations, and eulogies, if they focus on the personal life of the deceased.
- Collections of materials that serve as a source of, or substitute for, an account of a life, including the following:
  - Collections of correspondence (i.e. letters from one person to another, or to others) that include biographical information about the writer, but not correspondence about a particular event or topic not related to the writer's personal life.
  - Journals and diaries.
- Memoirs or reminiscences about the writer's personal life.
- Personal narratives of wars and events and first person accounts of trips or tours.
- Interviews and conversations, if they deal with the personal life of the interviewee.
- Genealogical works, if they also include biographical information.
- Collective biographies, e.g. *International Who's Who*; *Dictionary of American Biography*; etc.

#### c. Guidelines for omitting a biography code

Do not enter a biography code in field 008/34 for the following types of material:

- Collections of portraits, unless they are accompanied by biographical description.
- Genealogical works that do not include biographical information.
- Literary criticism, unless the work also includes biographical information.
- Biography of animals.
- Fictionalized biography.

#### d. Special considerations

**(1) Biography of a ruler vs. account of his or her reign.** Treat a work as biographical only if considerable attention is devoted to the ruler's personal life. Treat the work as history if the focus is on events that occurred during his or her reign. Examples:

```
Title: America's last king : an interpretation of the madness of George III.
[Code b in field 008/34 for individual biography]

Title: Memoirs of the reign of George III to the commencement of the year 1799.
[Do not code for biography]
```

**(2) Persons associated with doctrines or movements.** Do not treat a work as biographical if the focus is mainly on the intellectual content of the doctrine or movement rather than on the personal life of the proponent. Example:

```
Title: The history and character of Calvinism.
[Do not code for biography]
```
