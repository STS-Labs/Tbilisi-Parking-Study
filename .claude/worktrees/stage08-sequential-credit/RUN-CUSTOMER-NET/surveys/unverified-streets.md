# Unverified streets — adjudicate on the ground

**80 streets, 5.40 km.** These are in the customer's `Streets.shp` and the routing network cannot carry them, so the plan drives them on **synthesised attributes**: two-way `residential` at the default residential speed (30 km/h free flow), no lane count, no width, no turn restrictions.


## Read this first — OSM does know about these streets

Not one of them is absent from OpenStreetMap. Every one has an OSM way underneath it that the drivability filter excluded, and *why* it was excluded is the most useful thing on this page:

| OSM says | streets |
| --- | ---: |
| construction / class_excluded | 51 |
| footway / class_excluded | 10 |
| residential / access_private | 10 |
| residential / barrier_blocking | 6 |
| residential / access_no | 1 |
| service / access_private | 1 |
| steps / class_excluded | 1 |

`construction` means OSM believes the street is being built. `access_private` and `barrier_blocking` mean OSM believes there is a gate or a bollard. `class_excluded` on a `footway`, `pedestrian` or `steps` means the customer digitised something that is not a road at all. Each of those is a different answer to "why can we not drive here", and the driver settles it in one look.


## What the driver has to settle

1. **Can the car get in at all?** A gate, a bollard or a building site ends the question — report it and the street comes out of the required set.
2. **One-way signage.** The plan assumes two-way. A one-way street driven against the arrow is a legality and safety problem, not a modelling nicety, and there is no data anywhere that can settle it in software.
3. **Width.** Two-way `residential` with no width is treated as a narrow pair — one pass covers both sides. A wide street needs two.
4. **Junction control.** No turn restriction is modelled at either end.


Correct any of these and the fix belongs in OpenStreetMap, not in this repository: every future run of every future campaign then gets it for free.


## The streets

| # | Length m | Centre lon | Centre lat | OSM says | Way id |
| ---: | ---: | ---: | ---: | --- | ---: |
| 1 | 222.6 | 44.797130 | 41.699610 | construction / class_excluded | -56 |
| 2 | 214.8 | 44.800469 | 41.694862 | construction / class_excluded | -60 |
| 3 | 191.0 | 44.794416 | 41.701723 | construction / class_excluded | -48 |
| 4 | 182.4 | 44.748570 | 41.721209 | residential / access_private | -6 |
| 5 | 179.9 | 44.820002 | 41.693578 | residential / barrier_blocking | -79 |
| 6 | 168.6 | 44.707206 | 41.723376 | residential / access_private | -2 |
| 7 | 157.7 | 44.796891 | 41.699685 | construction / class_excluded | -54 |
| 8 | 150.6 | 44.798572 | 41.698046 | construction / class_excluded | -58 |
| 9 | 150.0 | 44.800603 | 41.694862 | construction / class_excluded | -63 |
| 10 | 143.4 | 44.791926 | 41.725758 | residential / barrier_blocking | -34 |
| 11 | 138.4 | 44.705962 | 41.723740 | footway / class_excluded | -1 |
| 12 | 120.4 | 44.795741 | 41.700751 | construction / class_excluded | -52 |
| 13 | 120.0 | 44.800663 | 41.704491 | residential / barrier_blocking | -62 |
| 14 | 119.3 | 44.799691 | 41.696239 | construction / class_excluded | -59 |
| 15 | 118.7 | 44.799984 | 41.695973 | construction / class_excluded | -61 |
| 16 | 117.5 | 44.805445 | 41.691120 | residential / access_private | -77 |
| 17 | 113.1 | 44.795740 | 41.693009 | residential / access_no | -51 |
| 18 | 108.8 | 44.802227 | 41.704895 | residential / barrier_blocking | -68 |
| 19 | 101.2 | 44.767352 | 41.721569 | residential / access_private | -7 |
| 20 | 98.8 | 44.798560 | 41.697877 | construction / class_excluded | -57 |
| 21 | 98.0 | 44.783801 | 41.702233 | construction / class_excluded | -12 |
| 22 | 97.3 | 44.803105 | 41.693941 | residential / barrier_blocking | -69 |
| 23 | 96.8 | 44.796686 | 41.691037 | steps / class_excluded | -50 |
| 24 | 94.8 | 44.789305 | 41.705062 | construction / class_excluded | -23 |
| 25 | 91.3 | 44.791188 | 41.703276 | footway / class_excluded | -31 |
| 26 | 89.0 | 44.825103 | 41.687827 | footway / class_excluded | -80 |
| 27 | 87.8 | 44.768070 | 41.720983 | footway / class_excluded | -8 |
| 28 | 86.9 | 44.794903 | 41.701442 | construction / class_excluded | -49 |
| 29 | 84.7 | 44.711085 | 41.719425 | residential / access_private | -5 |
| 30 | 77.9 | 44.797098 | 41.700474 | construction / class_excluded | -55 |
| 31 | 69.5 | 44.790756 | 41.703993 | construction / class_excluded | -28 |
| 32 | 68.0 | 44.801604 | 41.694029 | construction / class_excluded | -67 |
| 33 | 64.1 | 44.710002 | 41.719502 | residential / access_private | -3 |
| 34 | 63.2 | 44.790630 | 41.704073 | construction / class_excluded | -32 |
| 35 | 59.0 | 44.802932 | 41.703291 | footway / class_excluded | -70 |
| 36 | 57.8 | 44.789898 | 41.704543 | construction / class_excluded | -24 |
| 37 | 57.7 | 44.796476 | 41.700534 | construction / class_excluded | -53 |
| 38 | 57.5 | 44.786373 | 41.705713 | residential / access_private | -13 |
| 39 | 52.7 | 44.792135 | 41.702856 | construction / class_excluded | -33 |
| 40 | 52.0 | 44.787438 | 41.708155 | footway / class_excluded | -15 |
| 41 | 48.4 | 44.793419 | 41.702498 | construction / class_excluded | -45 |
| 42 | 45.1 | 44.803319 | 41.711380 | construction / class_excluded | -72 |
| 43 | 43.1 | 44.790350 | 41.704322 | construction / class_excluded | -30 |
| 44 | 41.0 | 44.792223 | 41.702961 | construction / class_excluded | -37 |
| 45 | 40.3 | 44.788523 | 41.705566 | construction / class_excluded | -22 |
| 46 | 39.2 | 44.801224 | 41.693835 | construction / class_excluded | -64 |
| 47 | 38.5 | 44.790566 | 41.703618 | construction / class_excluded | -29 |
| 48 | 37.8 | 44.787599 | 41.707891 | footway / class_excluded | -21 |
| 49 | 36.1 | 44.792988 | 41.702693 | construction / class_excluded | -42 |
| 50 | 35.2 | 44.792576 | 41.703085 | construction / class_excluded | -38 |
| 51 | 35.0 | 44.804045 | 41.690743 | residential / barrier_blocking | -76 |
| 52 | 34.7 | 44.786397 | 41.706021 | residential / access_private | -14 |
| 53 | 32.8 | 44.801425 | 41.693829 | construction / class_excluded | -66 |
| 54 | 32.5 | 44.767882 | 41.721738 | residential / access_private | -9 |
| 55 | 29.1 | 44.792615 | 41.702777 | construction / class_excluded | -36 |
| 56 | 27.6 | 44.790354 | 41.703927 | construction / class_excluded | -27 |
| 57 | 26.8 | 44.793176 | 41.702726 | construction / class_excluded | -47 |
| 58 | 24.8 | 44.803327 | 41.711559 | construction / class_excluded | -74 |
| 59 | 24.3 | 44.790168 | 41.704234 | construction / class_excluded | -25 |
| 60 | 23.5 | 44.792885 | 41.702821 | construction / class_excluded | -41 |
| 61 | 23.4 | 44.792508 | 41.702867 | construction / class_excluded | -35 |
| 62 | 23.3 | 44.792723 | 41.702846 | construction / class_excluded | -40 |
| 63 | 22.9 | 44.792799 | 41.702928 | construction / class_excluded | -43 |
| 64 | 22.7 | 44.710470 | 41.719427 | residential / access_private | -4 |
| 65 | 22.0 | 44.806578 | 41.690083 | footway / class_excluded | -78 |
| 66 | 21.8 | 44.787888 | 41.708450 | service / access_private | -20 |
| 67 | 17.2 | 44.793036 | 41.702897 | construction / class_excluded | -44 |
| 68 | 16.1 | 44.792566 | 41.702944 | construction / class_excluded | -39 |
| 69 | 16.1 | 44.793204 | 41.702826 | construction / class_excluded | -46 |
| 70 | 13.5 | 44.801243 | 41.693986 | construction / class_excluded | -65 |
| 71 | 12.8 | 44.767930 | 41.721538 | footway / class_excluded | -10 |
| 72 | 11.7 | 44.803145 | 41.711522 | construction / class_excluded | -73 |
| 73 | 11.5 | 44.790265 | 41.704090 | construction / class_excluded | -26 |
| 74 | 11.0 | 44.776510 | 41.725510 | construction / class_excluded | -11 |
| 75 | 8.5 | 44.803489 | 41.711514 | construction / class_excluded | -75 |
| 76 | 8.5 | 44.787569 | 41.708471 | footway / class_excluded | -16 |
| 77 | 7.3 | 44.787699 | 41.708460 | construction / class_excluded | -18 |
| 78 | 7.0 | 44.803117 | 41.711444 | construction / class_excluded | -71 |
| 79 | 3.0 | 44.787637 | 41.708463 | construction / class_excluded | -17 |
| 80 | 1.3 | 44.787750 | 41.708459 | construction / class_excluded | -19 |

*Generated by `efficientroute prepare-network`. Endpoints snapped onto an existing OSM node: 110 of 110, largest move 0.0 m.*
