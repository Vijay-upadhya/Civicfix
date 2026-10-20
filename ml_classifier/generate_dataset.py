"""Builds dataset.csv (description,category) from phrase templates. Synthetic data only."""
import csv
import itertools
import random
from pathlib import Path

random.seed(7)
PLACES = ["near the main gate", "beside the bus stop", "outside the market", "on 5th Main Road", "near the metro entrance",
          "in front of the school", "next to the park", "at the junction", "near the temple", "behind the hospital",
          "on the service road", "near my apartment", "in our lane", "close to the signal"]
TEMPLATES = {
    "pothole": ["Large pothole {p}", "Road has a deep hole {p}", "Broken road surface {p}, two-wheelers skid", "Road damage after rain {p}",
                "Big pothole causing traffic {p}", "The road has caved in {p}", "Deep potholes everywhere {p}", "Road hole is dangerous at night {p}"],
    "garbage": ["Garbage overflowing {p}", "Waste has not been collected for days {p}", "Trash piling up {p}", "Bin overflow and bad smell {p}",
                "Rubbish scattered on the street {p}", "Garbage truck did not come {p}", "Dustbin is full and spilling {p}", "Litter everywhere {p}"],
    "streetlight": ["Street lamp is not working at night {p}", "Broken streetlight {p}", "Street light not working for three nights {p}",
                    "Dark road because the lamp post is off {p}", "Lights not working on the whole stretch {p}", "Streetlight flickering and dim {p}",
                    "Lamp is out, area is completely dark {p}", "Street light pole bulb fused {p}"],
    "water": ["Water leaking from the pipe {p}", "Pipe burst and water flowing on road {p}", "Water leakage from the main line {p}",
              "Leaking pipe wasting drinking water {p}", "No water supply since morning {p}", "Burst pipe flooding the street {p}",
              "Water wastage from broken tap {p}", "Water line leakage {p}"],
    "drain": ["Drain is blocked after heavy rain {p}", "Blocked drain with sewage overflow {p}", "Sewage water on the road {p}",
              "Open manhole on the road {p}", "Clogged drain causing waterlogging {p}", "Drainage overflow and mosquitoes {p}",
              "Storm water drain choked {p}", "Drain blocked with plastic {p}"],
    "footpath": ["Footpath is broken {p}", "Damaged pavement tiles {p}", "Sidewalk is uneven and unsafe to walk {p}", "Walkway slabs missing {p}",
                 "Pedestrians cannot use the footpath {p}", "Footpath blocked by broken tiles {p}", "Pavement has collapsed {p}", "Cracked footpath {p}"],
    "traffic": ["Traffic signal not working {p}", "Signal timer is stuck on red {p}", "Traffic light is off and causing jams {p}",
                "Zebra crossing paint faded and signal broken {p}", "Signal lights blinking amber all day {p}", "Traffic signal pole damaged {p}",
                "Pedestrian signal does not turn green {p}", "Traffic lights out at the junction {p}"],
    "animal": ["Stray dogs chasing people {p}", "Stray cattle blocking the road {p}", "Pack of stray dogs barking all night {p}",
               "Dog bite incident reported {p}", "Stray cows on the road {p}", "Monkeys entering homes {p}", "Injured stray animal {p}", "Aggressive stray dog {p}"],
    "dumping": ["Illegal dumping of construction debris {p}", "Someone dumped waste in the empty plot {p}", "Dumping of building rubble {p}",
                "Trucks dump garbage at night {p}", "Illegal dumping site has formed {p}", "Debris dumped on the roadside {p}",
                "Dumped furniture and mattresses {p}", "Dumping of waste by a contractor {p}"],
    "safety": ["Exposed electric wire hanging low {p}", "Fallen tree blocking the road and dangerous {p}", "Unsafe lane with no lighting and harassment {p}",
               "Open wire near children {p}", "Accident prone spot with no railing {p}", "Dangerous broken electric box {p}",
               "Women feel unsafe walking here {p}", "Loose electric cable on the ground {p}"],
    "park": ["Park bench is broken {p}", "Playground swing damaged {p}", "Garden gate is broken and park is untidy {p}",
             "Public space needs repair {p}", "Park lights and benches vandalised {p}", "Children playground equipment is rusted {p}",
             "Park fence collapsed {p}", "Public garden is overgrown and damaged {p}"],
    "other": ["I want to suggest a new bus route {p}", "Noise from a loud event {p}", "Question about property tax receipts",
              "Please clarify the rules for hoardings {p}", "Request for a public toilet {p}", "General feedback about the ward office",
              "Need information about trade licences", "Encroachment by a shop {p}", "Nuisance from late night loudspeakers {p}", "Something is wrong, please check"],
}

rows = []
for cat, templates in TEMPLATES.items():
    combos = list(itertools.product(templates, PLACES))
    random.shuffle(combos)
    for t, p in combos[:44]:
        rows.append((t.replace(" {p}", "").strip() if "{p}" not in t else t.format(p=p), cat))
path = Path(__file__).parent / "dataset.csv"
with open(path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["description", "category"])
    w.writerows(rows)
print(f"wrote {len(rows)} rows to {path}")
