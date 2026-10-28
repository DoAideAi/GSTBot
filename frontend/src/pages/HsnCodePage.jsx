import { Link, useParams } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import RelatedTools from "../components/RelatedTools";
import SeoHead, { BASE_URL } from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { getByCode, searchHSN } from "../lib/hsnData";
import { formatINR } from "../lib/gstCalc";

const TOP_HSN_META = {
  "0101": { title: "HSN Code 0101 — Live horses, asses, mules and hinnies", keywords: "live, horses, asses, mules, hinnies, live animals" },
  "0102": { title: "HSN Code 0102 — Live bovine animals", keywords: "live, bovine, animals, live animals" },
  "0105": { title: "HSN Code 0105 — Live poultry", keywords: "live, poultry, fowls, ducks, geese, live animals" },
  "0106": { title: "HSN Code 0106 — Other live animals", keywords: "live, animals, live animals" },
  "0201": { title: "HSN Code 0201 — Meat of bovine animals, fresh or chilled", keywords: "meat, bovine, animals, fresh, chilled, food" },
  "0202": { title: "HSN Code 0202 — Frozen bovine meat", keywords: "frozen, bovine, meat" },
  "0203": { title: "HSN Code 0203 — Fresh, chilled or frozen pork", keywords: "fresh, chilled, frozen, pork, meat" },
  "0204": { title: "HSN Code 0204 — Fresh, chilled or frozen meat of sheep or goats", keywords: "fresh, chilled, frozen, meat, sheep" },
  "0207": { title: "HSN Code 0207 — Fresh, chilled or frozen poultry meat and offal", keywords: "fresh, chilled, frozen, poultry, meat" },
  "0208": { title: "HSN Code 0208 — Other fresh, chilled or frozen meat", keywords: "fresh, chilled, frozen, meat, rabbit" },
  "0210": { title: "HSN Code 0210 — Dried, salted or smoked meat and edible offal", keywords: "dried, salted, smoked, meat, edible" },
  "0301": { title: "HSN Code 0301 — Live fish", keywords: "live, fish" },
  "0302": { title: "HSN Code 0302 — Fresh or chilled fish", keywords: "fresh, chilled, fish, excluding, fillets" },
  "0303": { title: "HSN Code 0303 — Frozen fish", keywords: "frozen, fish, excluding, fillets" },
  "0304": { title: "HSN Code 0304 — Fish fillets and other fish meat", keywords: "fish, fillets, fish, meat, fresh" },
  "0305": { title: "HSN Code 0305 — Dried, salted or smoked fish; fish meal", keywords: "dried, salted, smoked, fish;, fish" },
  "0306": { title: "HSN Code 0306 — Crustaceans", keywords: "crustaceans, shrimps, crabs, lobsters, fresh, fish" },
  "0307": { title: "HSN Code 0307 — Molluscs", keywords: "molluscs, oysters, mussels, squid, octopus, fish" },
  "0401": { title: "HSN Code 0401 — Milk & Cream", keywords: "milk, cream, fresh milk, pasteurized milk" },
  "0402": { title: "HSN Code 0402 — Milk and cream, concentrated or sweetened", keywords: "milk, cream, concentrated, sweetened, food" },
  "0403": { title: "HSN Code 0403 — Buttermilk, curd, yogurt and kephir", keywords: "buttermilk, curd, yogurt, kephir, dairy" },
  "0404": { title: "HSN Code 0404 — Whey and modified whey products", keywords: "whey, modified, whey, products, dairy" },
  "0405": { title: "HSN Code 0405 — Butter and ghee", keywords: "butter, ghee, dairy" },
  "0406": { title: "HSN Code 0406 — Cheese and curd", keywords: "cheese, curd, food" },
  "0407": { title: "HSN Code 0407 — Birds' eggs in shell, fresh", keywords: "birds', eggs, shell, fresh, dairy" },
  "0408": { title: "HSN Code 0408 — Egg yolks", keywords: "egg, yolks, dried, cooked, preserved, dairy" },
  "0409": { title: "HSN Code 0409 — Natural honey", keywords: "natural, honey, dairy" },
  "0410": { title: "HSN Code 0410 — Edible products of animal origin not elsewhere specified", keywords: "edible, products, animal, origin, dairy" },
  "0504": { title: "HSN Code 0504 — Guts, bladders and stomachs of animals", keywords: "guts, bladders, stomachs, animals, animal products" },
  "0505": { title: "HSN Code 0505 — Skins and feathers of birds; down", keywords: "skins, feathers, birds;, down, animal products" },
  "0511": { title: "HSN Code 0511 — Animal semen; animal products not elsewhere specified", keywords: "animal, semen;, animal, products, animal products" },
  "0601": { title: "HSN Code 0601 — Bulbs, tubers, corms, crowns and rhizomes", keywords: "bulbs, tubers, corms, crowns, rhizomes, plants" },
  "0602": { title: "HSN Code 0602 — Live plants, cuttings and slips; mushroom spawn", keywords: "live, plants, cuttings, slips;, mushroom" },
  "0603": { title: "HSN Code 0603 — Cut flowers and flower buds for bouquets, fresh or dried", keywords: "cut, flowers, flower, buds, bouquets, plants" },
  "0604": { title: "HSN Code 0604 — Foliage, branches without flowers", keywords: "foliage, branches, without, flowers, plants" },
  "0701": { title: "HSN Code 0701 — Potatoes, fresh or chilled", keywords: "potatoes, fresh, chilled, food" },
  "0702": { title: "HSN Code 0702 — Tomatoes, fresh or chilled", keywords: "tomatoes, fresh, chilled, food" },
  "0703": { title: "HSN Code 0703 — Onions, shallots, garlic and leeks, fresh or chilled", keywords: "onions, shallots, garlic, leeks, fresh, vegetables" },
  "0704": { title: "HSN Code 0704 — Cabbages, cauliflowers, broccoli, fresh or chilled", keywords: "cabbages, cauliflowers, broccoli, fresh, chilled, vegetables" },
  "0706": { title: "HSN Code 0706 — Carrots, turnips, beetroot, radishes, fresh or chilled", keywords: "carrots, turnips, beetroot, radishes, fresh, vegetables" },
  "0707": { title: "HSN Code 0707 — Cucumbers and gherkins, fresh or chilled", keywords: "cucumbers, gherkins, fresh, chilled, vegetables" },
  "0708": { title: "HSN Code 0708 — Leguminous vegetables", keywords: "leguminous, vegetables, peas, beans, fresh" },
  "0709": { title: "HSN Code 0709 — Other fresh vegetables", keywords: "fresh, vegetables, mushrooms, capsicum, spinach" },
  "0710": { title: "HSN Code 0710 — Frozen vegetables", keywords: "frozen, vegetables, uncooked, cooked, steaming" },
  "0712": { title: "HSN Code 0712 — Dried vegetables, whole, cut, sliced or in powder", keywords: "dried, vegetables, whole, cut, sliced" },
  "0713": { title: "HSN Code 0713 — Dried Leguminous Vegetables (Dal)", keywords: "dal, lentils, beans, dried legumes, pulses" },
  "0801": { title: "HSN Code 0801 — Coconuts, brazil nuts and cashew nuts, fresh or dried", keywords: "coconuts, brazil, nuts, cashew, nuts, fruits" },
  "0802": { title: "HSN Code 0802 — Almonds, hazelnuts, walnuts, pistachios and other nuts", keywords: "almonds, hazelnuts, walnuts, pistachios, nuts, fruits" },
  "0803": { title: "HSN Code 0803 — Bananas and plantains, fresh or dried", keywords: "bananas, plantains, fresh, dried, fruits" },
  "0804": { title: "HSN Code 0804 — Dates, figs, pineapples, avocados, mangoes, fresh", keywords: "dates, figs, pineapples, avocados, mangoes, fruits" },
  "0805": { title: "HSN Code 0805 — Citrus fruit", keywords: "citrus, fruit, oranges, lemons, limes, fruits" },
  "0806": { title: "HSN Code 0806 — Grapes, fresh or dried", keywords: "grapes, fresh, dried, raisins, fruits" },
  "0807": { title: "HSN Code 0807 — Melons and papayas, fresh", keywords: "melons, papayas, fresh, fruits" },
  "0808": { title: "HSN Code 0808 — Apples, pears and quinces, fresh", keywords: "apples, pears, quinces, fresh, fruits" },
  "0809": { title: "HSN Code 0809 — Apricots, cherries, peaches, plums and sloes, fresh", keywords: "apricots, cherries, peaches, plums, sloes, fruits" },
  "0810": { title: "HSN Code 0810 — Strawberries, raspberries, kiwifruit and other fresh fruits", keywords: "strawberries, raspberries, kiwifruit, fresh, fruits" },
  "0811": { title: "HSN Code 0811 — Frozen fruits and nuts", keywords: "frozen, fruits, nuts, uncooked, steamed" },
  "0813": { title: "HSN Code 0813 — Dried fruits", keywords: "dried, fruits, apricots, prunes, raisins" },
  "0901": { title: "HSN Code 0901 — Coffee", keywords: "coffee, coffee beans, roasted coffee, instant coffee" },
  "0902": { title: "HSN Code 0902 — Tea", keywords: "tea, green tea, black tea, tea leaves" },
  "0903": { title: "HSN Code 0903 — Mate", keywords: "mate, spices" },
  "0904": { title: "HSN Code 0904 — Pepper", keywords: "pepper, black, white, long, capsicum, spices" },
  "0905": { title: "HSN Code 0905 — Vanilla beans", keywords: "vanilla, beans, spices" },
  "0906": { title: "HSN Code 0906 — Cinnamon and cinnamon-tree bark", keywords: "cinnamon, cinnamon-tree, bark, spices" },
  "0907": { title: "HSN Code 0907 — Cloves", keywords: "cloves, whole, fruit, cloves, stems, spices" },
  "0908": { title: "HSN Code 0908 — Nutmeg, mace and cardamoms", keywords: "nutmeg, mace, cardamoms, spices" },
  "0909": { title: "HSN Code 0909 — Seeds of anise, cumin, coriander, fennel", keywords: "seeds, anise, cumin, coriander, fennel, spices" },
  "0910": { title: "HSN Code 0910 — Ginger, turmeric, saffron, thyme, bay leaves, curry powder", keywords: "ginger, turmeric, saffron, thyme, bay, spices" },
  "1001": { title: "HSN Code 1001 — Wheat and meslin", keywords: "wheat, meslin, food" },
  "1002": { title: "HSN Code 1002 — Rye", keywords: "rye, cereals" },
  "1003": { title: "HSN Code 1003 — Barley", keywords: "barley, cereals" },
  "1004": { title: "HSN Code 1004 — Oats", keywords: "oats, cereals" },
  "1005": { title: "HSN Code 1005 — Maize", keywords: "maize, corn, food" },
  "1006": { title: "HSN Code 1006 — Rice", keywords: "rice, basmati, paddy, polished rice" },
  "1007": { title: "HSN Code 1007 — Grain sorghum", keywords: "grain, sorghum, jowar, cereals" },
  "1008": { title: "HSN Code 1008 — Millets, buckwheat, quinoa and other cereals", keywords: "millets, buckwheat, quinoa, cereals" },
  "1101": { title: "HSN Code 1101 — Wheat Flour (Atta)", keywords: "atta, wheat flour, maida, flour" },
  "1102": { title: "HSN Code 1102 — Cereal flours", keywords: "cereal, flours, wheat, meslin, milling" },
  "1103": { title: "HSN Code 1103 — Cereal groats, meal, pellets; semolina", keywords: "cereal, groats, meal, pellets;, semolina, milling" },
  "1104": { title: "HSN Code 1104 — Rolled, flaked or milled cereal grains", keywords: "rolled, flaked, milled, cereal, grains, milling" },
  "1105": { title: "HSN Code 1105 — Flour, meal, powder and flakes of potato", keywords: "flour, meal, powder, flakes, potato, milling" },
  "1106": { title: "HSN Code 1106 — Flour and meal of dried leguminous vegetables", keywords: "flour, meal, dried, leguminous, vegetables, milling" },
  "1107": { title: "HSN Code 1107 — Malt, whether or not roasted", keywords: "malt, roasted, milling" },
  "1108": { title: "HSN Code 1108 — Starches; inulin", keywords: "starches;, inulin, milling" },
  "1201": { title: "HSN Code 1201 — Soybeans, whether or not broken", keywords: "soybeans, broken, oil seeds" },
  "1202": { title: "HSN Code 1202 — Groundnuts", keywords: "groundnuts, peanuts, roasted, oil seeds" },
  "1205": { title: "HSN Code 1205 — Rape or colza seeds", keywords: "rape, colza, seeds, mustard, seeds, oil seeds" },
  "1206": { title: "HSN Code 1206 — Sunflower seeds, whether or not broken", keywords: "sunflower, seeds, broken, oil seeds" },
  "1207": { title: "HSN Code 1207 — Other oil seeds", keywords: "oil, seeds, sesame, safflower, linseed, oil seeds" },
  "1209": { title: "HSN Code 1209 — Seeds, fruits and spores for sowing", keywords: "seeds, fruits, spores, sowing, oil seeds" },
  "1210": { title: "HSN Code 1210 — Hop cones, fresh or dried; lupulin", keywords: "hop, cones, fresh, dried;, lupulin, oil seeds" },
  "1211": { title: "HSN Code 1211 — Medicinal plants", keywords: "medicinal, plants, tulsi, neem, ashwagandha, oil seeds" },
  "1212": { title: "HSN Code 1212 — Seaweed, sugar beet, sugar cane", keywords: "seaweed, sugar, beet, sugar, cane, oil seeds" },
  "1301": { title: "HSN Code 1301 — Lac, shellac and similar natural gums and resins", keywords: "lac, shellac, similar, natural, gums, gums & resins" },
  "1302": { title: "HSN Code 1302 — Vegetable saps and extracts", keywords: "vegetable, saps, extracts, henna, aloe, gums & resins" },
  "1401": { title: "HSN Code 1401 — Bamboo, rattan, reeds and similar materials", keywords: "bamboo, rattan, reeds, similar, materials, vegetable plaiting" },
  "1404": { title: "HSN Code 1404 — Other vegetable products not elsewhere specified", keywords: "vegetable, products, vegetable plaiting" },
  "1501": { title: "HSN Code 1501 — Animal fats and oils", keywords: "animal, fats, oils, food" },
  "1502": { title: "HSN Code 1502 — Rendered fats of bovine animals, sheep or goats", keywords: "rendered, fats, bovine, animals, sheep, fats & oils" },
  "1504": { title: "HSN Code 1504 — Fish oils and fats", keywords: "fish, oils, fats, cod, liver, fats & oils" },
  "1507": { title: "HSN Code 1507 — Soya-bean oil", keywords: "soya-bean, oil, food" },
  "1508": { title: "HSN Code 1508 — Groundnut", keywords: "groundnut, peanut, oil, fractions, fats & oils" },
  "1509": { title: "HSN Code 1509 — Olive oil, virgin", keywords: "olive, oil, virgin, fats & oils" },
  "1510": { title: "HSN Code 1510 — Other olive oils and blends", keywords: "olive, oils, blends, fats & oils" },
  "1511": { title: "HSN Code 1511 — Palm oil", keywords: "palm, oil, food" },
  "1512": { title: "HSN Code 1512 — Sunflower oil, safflower oil", keywords: "sunflower, oil, safflower, oil, food" },
  "1513": { title: "HSN Code 1513 — Coconut oil", keywords: "coconut, oil, copra, oil, fractions, fats & oils" },
  "1514": { title: "HSN Code 1514 — Rapeseed", keywords: "rapeseed, canola, mustard, oil, fats & oils" },
  "1515": { title: "HSN Code 1515 — Groundnut oil, olive oil, other fixed vegetable oils", keywords: "groundnut, oil, olive, oil, fixed, food" },
  "1516": { title: "HSN Code 1516 — Hydrogenated animal or vegetable fats", keywords: "hydrogenated, animal, vegetable, fats, vanaspati, fats & oils" },
  "1517": { title: "HSN Code 1517 — Margarine and edible preparations of fats", keywords: "margarine, edible, preparations, fats, fats & oils" },
  "1518": { title: "HSN Code 1518 — Animal or vegetable fats, boiled, oxidised or modified", keywords: "animal, vegetable, fats, boiled, oxidised, fats & oils" },
  "1520": { title: "HSN Code 1520 — Glycerol, crude; glycerol waters and lyes", keywords: "glycerol, crude;, glycerol, waters, lyes, fats & oils" },
  "1521": { title: "HSN Code 1521 — Vegetable waxes, beeswax and other insect waxes", keywords: "vegetable, waxes, beeswax, insect, waxes, fats & oils" },
  "1601": { title: "HSN Code 1601 — Sausages and similar products of meat or offal", keywords: "sausages, similar, products, meat, offal, prepared foods" },
  "1602": { title: "HSN Code 1602 — Prepared or preserved meat", keywords: "prepared, preserved, meat, corned, beef, prepared foods" },
  "1604": { title: "HSN Code 1604 — Prepared or preserved fish; caviar", keywords: "prepared, preserved, fish;, caviar, prepared foods" },
  "1605": { title: "HSN Code 1605 — Prepared or preserved crustaceans and molluscs", keywords: "prepared, preserved, crustaceans, molluscs, prepared foods" },
  "1701": { title: "HSN Code 1701 — Sugar (Cane or Beet)", keywords: "sugar, cane sugar, beet sugar, refined sugar" },
  "1702": { title: "HSN Code 1702 — Other sugars", keywords: "sugars, glucose, fructose, maltose, sugar & confectionery" },
  "1703": { title: "HSN Code 1703 — Molasses from sugar extraction or refining", keywords: "molasses, sugar, extraction, refining, sugar & confectionery" },
  "1704": { title: "HSN Code 1704 — Sugar confectionery", keywords: "sugar, confectionery, containing, cocoa, food" },
  "1801": { title: "HSN Code 1801 — Cocoa beans, whole or broken, raw or roasted", keywords: "cocoa, beans, whole, broken, raw" },
  "1803": { title: "HSN Code 1803 — Cocoa paste, whether or not defatted", keywords: "cocoa, paste, defatted" },
  "1804": { title: "HSN Code 1804 — Cocoa butter, fat and oil", keywords: "cocoa, butter, fat, oil" },
  "1805": { title: "HSN Code 1805 — Cocoa powder, not containing added sugar", keywords: "cocoa, powder, containing, added, sugar" },
  "1806": { title: "HSN Code 1806 — Chocolate and other food preparations containing cocoa", keywords: "chocolate, food, preparations, containing, cocoa" },
  "1901": { title: "HSN Code 1901 — Malt extract; food preparations of flour", keywords: "malt, extract;, food, preparations, flour" },
  "1902": { title: "HSN Code 1902 — Pasta, noodles, couscous and vermicelli", keywords: "pasta, noodles, couscous, vermicelli, cereal preparations" },
  "1903": { title: "HSN Code 1903 — Tapioca and substitutes from starch", keywords: "tapioca, substitutes, starch, sago, cereal preparations" },
  "1904": { title: "HSN Code 1904 — Prepared cereal-based foods", keywords: "prepared, cereal-based, foods, cornflakes, muesli, cereal preparations" },
  "1905": { title: "HSN Code 1905 — Bread, biscuits, cakes, pastry", keywords: "bread, biscuits, cakes, pastry, food" },
  "2001": { title: "HSN Code 2001 — Pickles; vegetables/fruits preserved in vinegar", keywords: "pickles;, vegetables, fruits, preserved, vinegar, prepared foods" },
  "2002": { title: "HSN Code 2002 — Tomatoes prepared or preserved", keywords: "tomatoes, prepared, preserved, tomato, paste, prepared foods" },
  "2003": { title: "HSN Code 2003 — Mushrooms and truffles prepared or preserved", keywords: "mushrooms, truffles, prepared, preserved, prepared foods" },
  "2004": { title: "HSN Code 2004 — Frozen prepared or preserved vegetables", keywords: "frozen, prepared, preserved, vegetables, prepared foods" },
  "2005": { title: "HSN Code 2005 — Other prepared vegetables", keywords: "prepared, vegetables, potato, chips, canned, prepared foods" },
  "2006": { title: "HSN Code 2006 — Vegetables, fruits, nuts preserved by sugar", keywords: "vegetables, fruits, nuts, preserved, sugar, prepared foods" },
  "2007": { title: "HSN Code 2007 — Jams, fruit jellies, marmalades and fruit pastes", keywords: "jams, fruit, jellies, marmalades, fruit, prepared foods" },
  "2008": { title: "HSN Code 2008 — Prepared nuts, peanut butter, fruits prepared", keywords: "prepared, nuts, peanut, butter, fruits, prepared foods" },
  "2009": { title: "HSN Code 2009 — Fruit juices and vegetable juices, unfermented", keywords: "fruit, juices, vegetable, juices, unfermented, beverages" },
  "2101": { title: "HSN Code 2101 — Coffee and tea extracts, essences and concentrates", keywords: "coffee, tea, extracts, essences, concentrates, prepared foods" },
  "2102": { title: "HSN Code 2102 — Yeast", keywords: "yeast, active, inactive;, baking, powders, prepared foods" },
  "2103": { title: "HSN Code 2103 — Sauces, ketchup, mustard, mixed condiments", keywords: "sauces, ketchup, mustard, mixed, condiments, prepared foods" },
  "2104": { title: "HSN Code 2104 — Soups and broths, preparations thereof", keywords: "soups, broths, preparations, thereof, prepared foods" },
  "2105": { title: "HSN Code 2105 — Ice cream and other edible ice", keywords: "ice, cream, edible, ice, prepared foods" },
  "2106": { title: "HSN Code 2106 — Food preparations not elsewhere specified", keywords: "food, preparations, namkeen, papad" },
  "2201": { title: "HSN Code 2201 — Waters, including mineral and aerated waters", keywords: "waters, mineral, aerated, waters, beverages" },
  "2202": { title: "HSN Code 2202 — Soft Drinks & Flavoured Water", keywords: "soft drink, cola, aerated water, cold drink" },
  "2203": { title: "HSN Code 2203 — Beer made from malt", keywords: "beer, made, malt, beverages" },
  "2204": { title: "HSN Code 2204 — Wine of fresh grapes", keywords: "wine, fresh, grapes, beverages" },
  "2207": { title: "HSN Code 2207 — Undenatured ethyl alcohol; denatured spirits", keywords: "undenatured, ethyl, alcohol;, denatured, spirits, beverages" },
  "2209": { title: "HSN Code 2209 — Vinegar and substitutes from acetic acid", keywords: "vinegar, substitutes, acetic, acid, beverages" },
  "2301": { title: "HSN Code 2301 — Flour, meals of meat/fish for animal feed", keywords: "flour, meals, meat, fish, animal, animal feed" },
  "2302": { title: "HSN Code 2302 — Bran, sharps and other residues of cereals", keywords: "bran, sharps, residues, cereals, animal feed" },
  "2304": { title: "HSN Code 2304 — Oil-cake and residues of soybean oil extraction", keywords: "oil-cake, residues, soybean, oil, extraction, animal feed" },
  "2306": { title: "HSN Code 2306 — Oil-cake and residues of other vegetable fats", keywords: "oil-cake, residues, vegetable, fats, animal feed" },
  "2309": { title: "HSN Code 2309 — Preparations for animal feeding", keywords: "preparations, animal, feeding, cattle, poultry, animal feed" },
  "2401": { title: "HSN Code 2401 — Unmanufactured tobacco; tobacco refuse", keywords: "unmanufactured, tobacco;, tobacco, refuse" },
  "2402": { title: "HSN Code 2402 — Cigars, cigarettes, tobacco", keywords: "cigars, cigarettes, tobacco" },
  "2403": { title: "HSN Code 2403 — Other manufactured tobacco", keywords: "manufactured, tobacco, gutka, pan, masala" },
  "2501": { title: "HSN Code 2501 — Common salt, sea salt, rock salt", keywords: "common, salt, sea, salt, rock, minerals" },
  "2505": { title: "HSN Code 2505 — Natural sands", keywords: "natural, sands, silica, quartz, industrial, minerals" },
  "2506": { title: "HSN Code 2506 — Quartz and quartzite", keywords: "quartz, quartzite, minerals" },
  "2510": { title: "HSN Code 2510 — Natural calcium phosphates and phosphatic chalk", keywords: "natural, calcium, phosphates, phosphatic, chalk, minerals" },
  "2515": { title: "HSN Code 2515 — Marble, travertine and calcareous stone", keywords: "marble, travertine, calcareous, stone, minerals" },
  "2516": { title: "HSN Code 2516 — Granite, sandstone and building stone", keywords: "granite, sandstone, building, stone, minerals" },
  "2517": { title: "HSN Code 2517 — Pebbles, gravel, broken or crushed stone; macadam", keywords: "pebbles, gravel, broken, crushed, stone;, minerals" },
  "2521": { title: "HSN Code 2521 — Limestone for cement manufacture", keywords: "limestone, cement, manufacture, minerals" },
  "2523": { title: "HSN Code 2523 — Portland Cement", keywords: "cement, portland cement, construction material" },
  "2601": { title: "HSN Code 2601 — Iron ores and concentrates", keywords: "iron, ores, concentrates" },
  "2602": { title: "HSN Code 2602 — Manganese ores and concentrates", keywords: "manganese, ores, concentrates" },
  "2603": { title: "HSN Code 2603 — Copper ores and concentrates", keywords: "copper, ores, concentrates" },
  "2606": { title: "HSN Code 2606 — Aluminium ores", keywords: "aluminium, ores, bauxite, concentrates" },
  "2701": { title: "HSN Code 2701 — Coal; briquettes and solid fuels from coal", keywords: "coal;, briquettes, solid, fuels, coal, mineral fuels" },
  "2702": { title: "HSN Code 2702 — Lignite, whether or not agglomerated", keywords: "lignite, agglomerated, mineral fuels" },
  "2704": { title: "HSN Code 2704 — Coke and semi-coke of coal, lignite or peat", keywords: "coke, semi-coke, coal, lignite, peat, mineral fuels" },
  "2706": { title: "HSN Code 2706 — Tar distilled from coal, lignite or peat", keywords: "tar, distilled, coal, lignite, peat, mineral fuels" },
  "2710": { title: "HSN Code 2710 — Petroleum oils", keywords: "petroleum, oils, petrol, diesel, atf, fuel" },
  "2711": { title: "HSN Code 2711 — Petroleum gases", keywords: "petroleum, gases, lpg, natural, gas, fuel" },
  "2713": { title: "HSN Code 2713 — Petroleum coke, petroleum bitumen and residues", keywords: "petroleum, coke, petroleum, bitumen, residues, mineral fuels" },
  "2801": { title: "HSN Code 2801 — Fluorine, chlorine, bromine and iodine", keywords: "fluorine, chlorine, bromine, iodine, chemicals" },
  "2803": { title: "HSN Code 2803 — Carbon", keywords: "carbon, carbon, blacks, forms, chemicals" },
  "2804": { title: "HSN Code 2804 — Hydrogen, nitrogen, oxygen, rare gases", keywords: "hydrogen, nitrogen, oxygen, rare, gases, chemicals" },
  "2806": { title: "HSN Code 2806 — Hydrochloric acid; chlorosulphuric acid", keywords: "hydrochloric, acid;, chlorosulphuric, acid, chemicals" },
  "2807": { title: "HSN Code 2807 — Sulphuric acid; oleum", keywords: "sulphuric, acid;, oleum, chemicals" },
  "2811": { title: "HSN Code 2811 — Other inorganic acids and oxygen compounds", keywords: "inorganic, acids, oxygen, compounds, chemicals" },
  "2814": { title: "HSN Code 2814 — Ammonia, anhydrous or in aqueous solution", keywords: "ammonia, anhydrous, aqueous, solution, chemicals" },
  "2815": { title: "HSN Code 2815 — Sodium hydroxide", keywords: "sodium, hydroxide, caustic, soda;, potassium, chemicals" },
  "2836": { title: "HSN Code 2836 — Carbonates; peroxocarbonates; sodium bicarbonate", keywords: "carbonates;, peroxocarbonates;, sodium, bicarbonate, chemicals" },
  "2901": { title: "HSN Code 2901 — Acyclic hydrocarbons", keywords: "acyclic, hydrocarbons, ethylene, propylene, chemicals" },
  "2902": { title: "HSN Code 2902 — Cyclic hydrocarbons", keywords: "cyclic, hydrocarbons, benzene, toluene, xylenes, chemicals" },
  "2905": { title: "HSN Code 2905 — Acyclic alcohols", keywords: "acyclic, alcohols, methanol, propanol, glycerol, chemicals" },
  "2915": { title: "HSN Code 2915 — Acetic acid, its salts and anhydrides", keywords: "acetic, acid, salts, anhydrides, chemicals" },
  "2933": { title: "HSN Code 2933 — Heterocyclic compounds with nitrogen hetero-atoms", keywords: "heterocyclic, compounds, nitrogen, hetero-atoms, chemicals" },
  "2936": { title: "HSN Code 2936 — Provitamins and vitamins, natural or synthesised", keywords: "provitamins, vitamins, natural, synthesised, chemicals" },
  "2937": { title: "HSN Code 2937 — Hormones, prostaglandins, thromboxanes", keywords: "hormones, prostaglandins, thromboxanes, chemicals" },
  "2941": { title: "HSN Code 2941 — Antibiotics", keywords: "antibiotics, chemicals" },
  "3001": { title: "HSN Code 3001 — Dried glands and organs for organotherapeutic uses", keywords: "dried, glands, organs, organotherapeutic, uses, pharmaceuticals" },
  "3002": { title: "HSN Code 3002 — Human/animal blood; antisera, vaccines, toxins", keywords: "human, animal, blood;, antisera, vaccines, pharmaceuticals" },
  "3003": { title: "HSN Code 3003 — Medicaments", keywords: "medicaments, unmixed, measured, doses, pharmaceuticals" },
  "3004": { title: "HSN Code 3004 — Medicaments & Pharmaceutical Products", keywords: "medicine, drugs, pharmaceutical, tablets, capsules" },
  "3005": { title: "HSN Code 3005 — Bandages, dressings, medical supplies", keywords: "bandages, dressings, medical, supplies, pharma" },
  "3006": { title: "HSN Code 3006 — Pharmaceutical preparations", keywords: "pharmaceutical, preparations, surgical, sutures, blood-grouping, pharma" },
  "3101": { title: "HSN Code 3101 — Animal or vegetable fertilisers; guano", keywords: "animal, vegetable, fertilisers;, guano, fertilizers" },
  "3102": { title: "HSN Code 3102 — Mineral or chemical nitrogenous fertilisers", keywords: "mineral, chemical, nitrogenous, fertilisers, urea, fertilizers" },
  "3103": { title: "HSN Code 3103 — Mineral or chemical phosphatic fertilisers", keywords: "mineral, chemical, phosphatic, fertilisers, fertilizers" },
  "3104": { title: "HSN Code 3104 — Mineral or chemical potassic fertilisers", keywords: "mineral, chemical, potassic, fertilisers, fertilizers" },
  "3105": { title: "HSN Code 3105 — Mineral/chemical fertilisers with two or more nutrients", keywords: "mineral, chemical, fertilisers, two, more, fertilizers" },
  "3201": { title: "HSN Code 3201 — Tanning extracts of vegetable origin; tannins", keywords: "tanning, extracts, vegetable, origin;, tannins, dyes & pigments" },
  "3204": { title: "HSN Code 3204 — Synthetic colouring matter; dyes", keywords: "synthetic, colouring, matter;, dyes, chemicals" },
  "3205": { title: "HSN Code 3205 — Colour lakes; preparations based on colour lakes", keywords: "colour, lakes;, preparations, based, colour, dyes & pigments" },
  "3206": { title: "HSN Code 3206 — Inorganic pigments", keywords: "inorganic, pigments, titanium, dioxide, chrome, dyes & pigments" },
  "3207": { title: "HSN Code 3207 — Prepared pigments and colours for ceramics", keywords: "prepared, pigments, colours, ceramics, dyes & pigments" },
  "3208": { title: "HSN Code 3208 — Paints & Varnishes", keywords: "paint, varnish, enamel, wall paint, primer" },
  "3209": { title: "HSN Code 3209 — Water-based paints and varnishes", keywords: "water-based, paints, varnishes, emulsions" },
  "3210": { title: "HSN Code 3210 — Other paints and varnishes; prepared water pigments", keywords: "paints, varnishes;, prepared, water, pigments" },
  "3213": { title: "HSN Code 3213 — Artists' colours", keywords: "artists', colours, chemicals" },
  "3214": { title: "HSN Code 3214 — Glaziers putty, grafting putty, resin cements", keywords: "glaziers, putty, grafting, putty, resin, paints" },
  "3215": { title: "HSN Code 3215 — Printing ink, writing or drawing ink", keywords: "printing, ink, writing, drawing, ink, dyes & pigments" },
  "3301": { title: "HSN Code 3301 — Essential oils", keywords: "essential, oils, lemon, peppermint, eucalyptus, perfumery" },
  "3302": { title: "HSN Code 3302 — Mixtures of odoriferous substances for food industry", keywords: "mixtures, odoriferous, substances, food, industry, perfumery" },
  "3303": { title: "HSN Code 3303 — Perfumes and toilet waters", keywords: "perfumes, toilet, waters, eau, toilette, perfumery" },
  "3304": { title: "HSN Code 3304 — Beauty & Skincare Products", keywords: "cosmetics, lipstick, face cream, skincare, makeup" },
  "3305": { title: "HSN Code 3305 — Hair Care Preparations", keywords: "shampoo, conditioner, hair oil, hair care" },
  "3306": { title: "HSN Code 3306 — Oral Hygiene (Toothpaste)", keywords: "toothpaste, mouthwash, dental hygiene, oral care" },
  "3307": { title: "HSN Code 3307 — Deodorants, bath preparations, room fresheners", keywords: "deodorants, bath, preparations, room, fresheners, perfumery" },
  "3401": { title: "HSN Code 3401 — Soap & Washing Preparations", keywords: "soap, detergent, washing powder, cleaning" },
  "3402": { title: "HSN Code 3402 — Cleaning preparations, surface-active agents", keywords: "cleaning, preparations, surface-active, agents, household" },
  "3403": { title: "HSN Code 3403 — Lubricating preparations", keywords: "lubricating, preparations, cutting, oil, rust, soap & cleaning" },
  "3405": { title: "HSN Code 3405 — Polishes and creams for footwear, furniture, floors", keywords: "polishes, creams, footwear, furniture, floors, soap & cleaning" },
  "3406": { title: "HSN Code 3406 — Candles, tapers and the like", keywords: "candles, tapers, like, soap & cleaning" },
  "3501": { title: "HSN Code 3501 — Casein, caseinates and other casein derivatives", keywords: "casein, caseinates, casein, derivatives, protein substances" },
  "3503": { title: "HSN Code 3503 — Gelatin and gelatin derivatives; isinglass", keywords: "gelatin, gelatin, derivatives;, isinglass, protein substances" },
  "3506": { title: "HSN Code 3506 — Prepared glues and adhesives not elsewhere specified", keywords: "prepared, glues, adhesives, protein substances" },
  "3604": { title: "HSN Code 3604 — Fireworks, signalling flares, rain rockets", keywords: "fireworks, signalling, flares, rain, rockets, explosives" },
  "3605": { title: "HSN Code 3605 — Matches", keywords: "matches, pyrotechnic, articles, explosives" },
  "3701": { title: "HSN Code 3701 — Photographic plates and film, sensitised", keywords: "photographic, plates, film, sensitised, photography" },
  "3702": { title: "HSN Code 3702 — Photographic film in rolls, sensitised", keywords: "photographic, film, rolls, sensitised, photography" },
  "3802": { title: "HSN Code 3802 — Activated carbon; activated natural mineral products", keywords: "activated, carbon;, activated, natural, mineral, chemicals" },
  "3808": { title: "HSN Code 3808 — Insecticides, fungicides, herbicides", keywords: "insecticides, fungicides, herbicides, chemicals" },
  "3814": { title: "HSN Code 3814 — Organic composite solvents and thinners", keywords: "organic, composite, solvents, thinners, chemicals" },
  "3822": { title: "HSN Code 3822 — Diagnostic or laboratory reagents on a backing", keywords: "diagnostic, laboratory, reagents, backing, chemicals" },
  "3826": { title: "HSN Code 3826 — Biodiesel and mixtures thereof", keywords: "biodiesel, mixtures, thereof, chemicals" },
  "3901": { title: "HSN Code 3901 — Polyethylene in primary forms", keywords: "polyethylene, primary, forms, plastics" },
  "3902": { title: "HSN Code 3902 — Polypropylene in primary forms", keywords: "polypropylene, primary, forms, plastics" },
  "3903": { title: "HSN Code 3903 — Polystyrene in primary forms", keywords: "polystyrene, primary, forms, plastics" },
  "3904": { title: "HSN Code 3904 — PVC", keywords: "pvc, polyvinyl, chloride, primary, forms, plastics" },
  "3906": { title: "HSN Code 3906 — Acrylic polymers in primary forms", keywords: "acrylic, polymers, primary, forms, plastics" },
  "3907": { title: "HSN Code 3907 — Polyacetals, polyesters in primary forms", keywords: "polyacetals, polyesters, primary, forms, plastics" },
  "3909": { title: "HSN Code 3909 — Amino resins, phenolic resins in primary forms", keywords: "amino, resins, phenolic, resins, primary, plastics" },
  "3917": { title: "HSN Code 3917 — Tubes, pipes and hoses of plastics", keywords: "tubes, pipes, hoses, plastics" },
  "3918": { title: "HSN Code 3918 — Plastic floor coverings, wall/ceiling coverings", keywords: "plastic, floor, coverings, wall, ceiling, plastics" },
  "3919": { title: "HSN Code 3919 — Self-adhesive plates, sheets, film of plastics", keywords: "self-adhesive, plates, sheets, film, plastics" },
  "3920": { title: "HSN Code 3920 — Plastic plates, sheets, film", keywords: "plastic, plates, sheets, film, packaging, plastics" },
  "3921": { title: "HSN Code 3921 — Plastic plates, sheets", keywords: "plastic, plates, sheets, cellular, plastics" },
  "3922": { title: "HSN Code 3922 — Plastic baths, sinks, wash basins, toilets", keywords: "plastic, baths, sinks, wash, basins, plastics" },
  "3923": { title: "HSN Code 3923 — Plastic containers, bottles, bags", keywords: "plastic, containers, bottles, bags, plastics" },
  "3924": { title: "HSN Code 3924 — Plastic tableware, kitchenware, household articles", keywords: "plastic, tableware, kitchenware, household, articles, plastics" },
  "3925": { title: "HSN Code 3925 — Plastic builders' ware", keywords: "plastic, builders', ware, doors, windows, plastics" },
  "3926": { title: "HSN Code 3926 — Other articles of plastics", keywords: "articles, plastics" },
  "4001": { title: "HSN Code 4001 — Natural rubber in primary forms", keywords: "natural, rubber, primary, forms" },
  "4002": { title: "HSN Code 4002 — Synthetic rubber in primary forms", keywords: "synthetic, rubber, primary, forms" },
  "4008": { title: "HSN Code 4008 — Vulcanised rubber plates, sheets, strips", keywords: "vulcanised, rubber, plates, sheets, strips" },
  "4009": { title: "HSN Code 4009 — Rubber tubes, pipes and hoses", keywords: "rubber, tubes, pipes, hoses" },
  "4010": { title: "HSN Code 4010 — Conveyor/transmission belts of vulcanised rubber", keywords: "conveyor, transmission, belts, vulcanised, rubber" },
  "4011": { title: "HSN Code 4011 — Pneumatic Tyres", keywords: "tyre, tire, rubber tyre, car tyre, bike tyre" },
  "4012": { title: "HSN Code 4012 — Retreaded or used pneumatic tyres of rubber", keywords: "retreaded, used, pneumatic, tyres, rubber" },
  "4013": { title: "HSN Code 4013 — Inner tubes of rubber", keywords: "inner, tubes, rubber" },
  "4014": { title: "HSN Code 4014 — Rubber hygienic/pharmaceutical articles, teats", keywords: "rubber, hygienic, pharmaceutical, articles, teats" },
  "4015": { title: "HSN Code 4015 — Rubber garments, gloves, mittens", keywords: "rubber, garments, gloves, mittens" },
  "4016": { title: "HSN Code 4016 — Other articles of vulcanised rubber", keywords: "articles, vulcanised, rubber, erasers, gaskets" },
  "4101": { title: "HSN Code 4101 — Raw hides and skins of bovine/equine animals", keywords: "raw, hides, skins, bovine, equine, leather" },
  "4104": { title: "HSN Code 4104 — Tanned/crust leather of bovine/equine animals", keywords: "tanned, crust, leather, bovine, equine" },
  "4107": { title: "HSN Code 4107 — Leather of other animals, tanned or crust", keywords: "leather, animals, tanned, crust" },
  "4201": { title: "HSN Code 4201 — Saddlery and harness for animals", keywords: "saddlery, harness, animals, leather goods" },
  "4202": { title: "HSN Code 4202 — Trunks, suitcases, handbags, wallets", keywords: "trunks, suitcases, handbags, wallets, leather" },
  "4203": { title: "HSN Code 4203 — Leather garments, gloves, belts", keywords: "leather, garments, gloves, belts" },
  "4205": { title: "HSN Code 4205 — Other articles of leather or composition leather", keywords: "articles, leather, composition, leather, leather goods" },
  "4301": { title: "HSN Code 4301 — Raw furskins, heads, tails, paws", keywords: "raw, furskins, heads, tails, paws" },
  "4303": { title: "HSN Code 4303 — Articles of apparel and accessories of furskin", keywords: "articles, apparel, accessories, furskin, furskins" },
  "4401": { title: "HSN Code 4401 — Fuel wood, wood chips, sawdust", keywords: "fuel, wood, wood, chips, sawdust" },
  "4403": { title: "HSN Code 4403 — Wood in the rough, treated or untreated", keywords: "wood, rough, treated, untreated" },
  "4407": { title: "HSN Code 4407 — Wood sawn or chipped lengthwise, sliced/peeled", keywords: "wood, sawn, chipped, lengthwise, sliced" },
  "4408": { title: "HSN Code 4408 — Veneer sheets, sheets for plywood", keywords: "veneer, sheets, sheets, plywood, wood" },
  "4410": { title: "HSN Code 4410 — Particle board and oriented strand board", keywords: "particle, board, oriented, strand, board, wood" },
  "4411": { title: "HSN Code 4411 — Fibreboard, MDF of wood or ligneous materials", keywords: "fibreboard, mdf, wood, ligneous, materials" },
  "4412": { title: "HSN Code 4412 — Plywood, veneered panels, laminated wood", keywords: "plywood, veneered, panels, laminated, wood" },
  "4415": { title: "HSN Code 4415 — Wooden packing cases, boxes, crates, pallets", keywords: "wooden, packing, cases, boxes, crates, wood" },
  "4418": { title: "HSN Code 4418 — Builders' joinery", keywords: "builders', joinery, doors, windows, parquet, wood" },
  "4419": { title: "HSN Code 4419 — Wooden tableware and kitchenware", keywords: "wooden, tableware, kitchenware, wood" },
  "4421": { title: "HSN Code 4421 — Other articles of wood", keywords: "articles, wood, pegs, hangers, spools" },
  "4601": { title: "HSN Code 4601 — Plaits, basketwork, wickerwork products", keywords: "plaits, basketwork, wickerwork, products, straw & plaiting" },
  "4602": { title: "HSN Code 4602 — Basketwork, wickerwork articles, loofah", keywords: "basketwork, wickerwork, articles, loofah, straw & plaiting" },
  "4801": { title: "HSN Code 4801 — Newsprint, in rolls or sheets", keywords: "newsprint, rolls, sheets, paper" },
  "4802": { title: "HSN Code 4802 — Paper and paperboard, uncoated", keywords: "paper, paperboard, uncoated" },
  "4804": { title: "HSN Code 4804 — Uncoated kraft paper and paperboard", keywords: "uncoated, kraft, paper, paperboard" },
  "4808": { title: "HSN Code 4808 — Corrugated paper and paperboard", keywords: "corrugated, paper, paperboard" },
  "4810": { title: "HSN Code 4810 — Coated paper and paperboard", keywords: "coated, paper, paperboard" },
  "4811": { title: "HSN Code 4811 — Paper, coated, impregnated", keywords: "paper, coated, impregnated" },
  "4817": { title: "HSN Code 4817 — Envelopes, letter cards, postcards of paper", keywords: "envelopes, letter, cards, postcards, paper" },
  "4818": { title: "HSN Code 4818 — Toilet paper, tissues, napkins of paper", keywords: "toilet, paper, tissues, napkins, paper" },
  "4819": { title: "HSN Code 4819 — Cartons, boxes, bags of paper", keywords: "cartons, boxes, bags, paper" },
  "4820": { title: "HSN Code 4820 — Registers, notebooks, diaries", keywords: "registers, notebooks, diaries, paper" },
  "4821": { title: "HSN Code 4821 — Paper labels and tags, printed or not", keywords: "paper, labels, tags, printed" },
  "4901": { title: "HSN Code 4901 — Printed Books & Brochures", keywords: "books, printed books, brochures, leaflets" },
  "4902": { title: "HSN Code 4902 — Newspapers, journals, periodicals", keywords: "newspapers, journals, periodicals, paper" },
  "5001": { title: "HSN Code 5001 — Silk-worm cocoons suitable for reeling", keywords: "silk-worm, cocoons, suitable, reeling, silk" },
  "5004": { title: "HSN Code 5004 — Silk yarn", keywords: "silk, yarn, waste, retail" },
  "5007": { title: "HSN Code 5007 — Woven fabrics of silk", keywords: "woven, fabrics, silk, textiles" },
  "5201": { title: "HSN Code 5201 — Cotton, not carded or combed", keywords: "cotton, carded, combed, raw, cotton" },
  "5204": { title: "HSN Code 5204 — Cotton sewing thread, retail or not", keywords: "cotton, sewing, thread, retail" },
  "5205": { title: "HSN Code 5205 — Cotton yarn", keywords: "cotton, yarn, sewing, thread, 85%+" },
  "5208": { title: "HSN Code 5208 — Woven Cotton Fabrics", keywords: "cotton fabric, cotton cloth, woven cotton" },
  "5209": { title: "HSN Code 5209 — Woven fabrics of cotton", keywords: "woven, fabrics, cotton, above, 200g, textiles" },
  "5210": { title: "HSN Code 5210 — Woven cotton fabric with man-made fibre, denim", keywords: "woven, cotton, fabric, man-made, fibre" },
  "5303": { title: "HSN Code 5303 — Jute and other textile bast fibres, raw", keywords: "jute, textile, bast, fibres, raw, textiles" },
  "5305": { title: "HSN Code 5305 — Coconut, abaca, sisal and other plant fibres", keywords: "coconut, abaca, sisal, plant, fibres, textiles" },
  "5310": { title: "HSN Code 5310 — Woven fabrics of jute or other bast fibres", keywords: "woven, fabrics, jute, bast, fibres, textiles" },
  "5402": { title: "HSN Code 5402 — Synthetic filament yarn, not for retail sale", keywords: "synthetic, filament, yarn, retail, sale, textiles" },
  "5407": { title: "HSN Code 5407 — Woven Synthetic Fabrics", keywords: "polyester fabric, nylon fabric, synthetic cloth" },
  "5503": { title: "HSN Code 5503 — Synthetic staple fibres, not carded/combed", keywords: "synthetic, staple, fibres, carded, combed, textiles" },
  "5509": { title: "HSN Code 5509 — Yarn of synthetic staple fibres, not retail", keywords: "yarn, synthetic, staple, fibres, retail, textiles" },
  "5512": { title: "HSN Code 5512 — Woven fabrics of synthetic staple fibres, 85%+", keywords: "woven, fabrics, synthetic, staple, fibres, textiles" },
  "5513": { title: "HSN Code 5513 — Woven fabrics of synthetic staple fibres", keywords: "woven, fabrics, synthetic, staple, fibres, textiles" },
  "5601": { title: "HSN Code 5601 — Wadding of textile materials and articles", keywords: "wadding, textile, materials, articles, textiles" },
  "5603": { title: "HSN Code 5603 — Nonwovens, whether or not impregnated/coated", keywords: "nonwovens, impregnated, coated, textiles" },
  "5607": { title: "HSN Code 5607 — Twine, cordage, ropes and cables", keywords: "twine, cordage, ropes, cables, textiles" },
  "5608": { title: "HSN Code 5608 — Knotted netting of twine, rope", keywords: "knotted, netting, twine, rope, fishing, textiles" },
  "5701": { title: "HSN Code 5701 — Carpets, hand-knotted or hand-woven", keywords: "carpets, hand-knotted, hand-woven, textiles" },
  "5702": { title: "HSN Code 5702 — Carpets, woven, not tufted or flocked", keywords: "carpets, woven, tufted, flocked, textiles" },
  "5703": { title: "HSN Code 5703 — Carpets, tufted, whether or not made up", keywords: "carpets, tufted, made, textiles" },
  "5903": { title: "HSN Code 5903 — Textile fabrics, impregnated, coated, laminated", keywords: "textile, fabrics, impregnated, coated, laminated, textiles" },
  "6001": { title: "HSN Code 6001 — Pile fabrics, knitted or crocheted", keywords: "pile, fabrics, knitted, crocheted, textiles" },
  "6101": { title: "HSN Code 6101 — Men's overcoats, jackets", keywords: "men's, overcoats, jackets, knitted, garments" },
  "6102": { title: "HSN Code 6102 — Women's overcoats, cloaks, knitted", keywords: "women's, overcoats, cloaks, knitted, apparel" },
  "6103": { title: "HSN Code 6103 — Men's suits, jackets, trousers, knitted", keywords: "men's, suits, jackets, trousers, knitted, apparel" },
  "6104": { title: "HSN Code 6104 — Women's suits, dresses, skirts", keywords: "women's, suits, dresses, skirts, knitted, garments" },
  "6105": { title: "HSN Code 6105 — Men's shirts, knitted or crocheted", keywords: "men's, shirts, knitted, crocheted, apparel" },
  "6106": { title: "HSN Code 6106 — Women's blouses and shirts, knitted", keywords: "women's, blouses, shirts, knitted, apparel" },
  "6107": { title: "HSN Code 6107 — Men's underpants, pyjamas, robes, knitted", keywords: "men's, underpants, pyjamas, robes, knitted, apparel" },
  "6108": { title: "HSN Code 6108 — Women's slips, petticoats, briefs, knitted", keywords: "women's, slips, petticoats, briefs, knitted, apparel" },
  "6109": { title: "HSN Code 6109 — T-Shirts & Vests (Knitted)", keywords: "t-shirt, vest, singlet, knitted garment" },
  "6110": { title: "HSN Code 6110 — Jerseys, pullovers, cardigans", keywords: "jerseys, pullovers, cardigans, knitted, garments" },
  "6111": { title: "HSN Code 6111 — Babies' garments and accessories, knitted", keywords: "babies', garments, accessories, knitted, apparel" },
  "6112": { title: "HSN Code 6112 — Track suits, ski suits, swimwear, knitted", keywords: "track, suits, ski, suits, swimwear, apparel" },
  "6114": { title: "HSN Code 6114 — Other garments, knitted or crocheted", keywords: "garments, knitted, crocheted, apparel" },
  "6115": { title: "HSN Code 6115 — Hosiery, stockings, socks, knitted", keywords: "hosiery, stockings, socks, knitted, apparel" },
  "6116": { title: "HSN Code 6116 — Gloves, mittens, mitts, knitted", keywords: "gloves, mittens, mitts, knitted, apparel" },
  "6201": { title: "HSN Code 6201 — Men's overcoats, cloaks, wind-jackets", keywords: "men's, overcoats, cloaks, wind-jackets, apparel" },
  "6202": { title: "HSN Code 6202 — Women's overcoats, cloaks, wind-jackets", keywords: "women's, overcoats, cloaks, wind-jackets, apparel" },
  "6203": { title: "HSN Code 6203 — Men's Suits, Trousers & Shorts", keywords: "trousers, pants, shorts, men's garments, jeans" },
  "6204": { title: "HSN Code 6204 — Women's Suits, Trousers & Skirts", keywords: "women's clothing, trousers, skirts, dresses" },
  "6205": { title: "HSN Code 6205 — Men's Shirts", keywords: "shirt, men's shirt, formal shirt, casual shirt" },
  "6206": { title: "HSN Code 6206 — Women's blouses, shirts", keywords: "women's, blouses, shirts, garments" },
  "6207": { title: "HSN Code 6207 — Men's singlets, undershirts, pyjamas", keywords: "men's, singlets, undershirts, pyjamas, apparel" },
  "6208": { title: "HSN Code 6208 — Women's singlets, slips, petticoats", keywords: "women's, singlets, slips, petticoats, apparel" },
  "6209": { title: "HSN Code 6209 — Babies' garments and accessories, not knitted", keywords: "babies', garments, accessories, knitted, apparel" },
  "6211": { title: "HSN Code 6211 — Track suits, ski suits, swimwear, not knitted", keywords: "track, suits, ski, suits, swimwear, apparel" },
  "6212": { title: "HSN Code 6212 — Brassieres, girdles, corsets, suspenders", keywords: "brassieres, girdles, corsets, suspenders, apparel" },
  "6213": { title: "HSN Code 6213 — Handkerchiefs of textile materials", keywords: "handkerchiefs, textile, materials, apparel" },
  "6214": { title: "HSN Code 6214 — Shawls, scarves, mufflers, veils", keywords: "shawls, scarves, mufflers, veils, apparel" },
  "6215": { title: "HSN Code 6215 — Ties, bow ties, cravats", keywords: "ties, bow, ties, cravats, apparel" },
  "6301": { title: "HSN Code 6301 — Blankets and travelling rugs", keywords: "blankets, travelling, rugs, textiles" },
  "6302": { title: "HSN Code 6302 — Bed linen, table linen, toilet/kitchen linen", keywords: "bed, linen, table, linen, toilet, textiles" },
  "6303": { title: "HSN Code 6303 — Curtains, drapes, interior blinds of textile", keywords: "curtains, drapes, interior, blinds, textile, textiles" },
  "6304": { title: "HSN Code 6304 — Furnishing articles", keywords: "furnishing, articles, bedspreads, cushions, textiles" },
  "6305": { title: "HSN Code 6305 — Sacks and bags for packing of textile", keywords: "sacks, bags, packing, textile, textiles" },
  "6306": { title: "HSN Code 6306 — Tarpaulins, tents, sails, camping goods", keywords: "tarpaulins, tents, sails, camping, goods, textiles" },
  "6307": { title: "HSN Code 6307 — Floor cloths, dish cloths, dusters, life jackets", keywords: "floor, cloths, dish, cloths, dusters, textiles" },
  "6401": { title: "HSN Code 6401 — Waterproof footwear", keywords: "waterproof, footwear" },
  "6402": { title: "HSN Code 6402 — Rubber/Plastic Footwear", keywords: "shoes, sandals, slippers, footwear, rubber shoes" },
  "6403": { title: "HSN Code 6403 — Leather Footwear", keywords: "leather shoes, leather footwear, formal shoes" },
  "6404": { title: "HSN Code 6404 — Footwear with textile uppers, rubber/plastic soles", keywords: "footwear, textile, uppers, rubber, plastic" },
  "6405": { title: "HSN Code 6405 — Other footwear", keywords: "footwear, wooden, cork, uppers" },
  "6406": { title: "HSN Code 6406 — Parts of footwear", keywords: "parts, footwear, uppers, soles, heels" },
  "6505": { title: "HSN Code 6505 — Hats and headgear, knitted or from lace/felt", keywords: "hats, headgear, knitted, lace, felt" },
  "6506": { title: "HSN Code 6506 — Safety headgear, helmets, hard hats", keywords: "safety, headgear, helmets, hard, hats" },
  "6601": { title: "HSN Code 6601 — Umbrellas and sun umbrellas", keywords: "umbrellas, sun, umbrellas" },
  "6602": { title: "HSN Code 6602 — Walking sticks, seat-sticks, whips, crops", keywords: "walking, sticks, seat-sticks, whips, crops, umbrellas" },
  "6702": { title: "HSN Code 6702 — Artificial flowers, foliage, fruit", keywords: "artificial, flowers, foliage, fruit, feathers & artificial flowers" },
  "6704": { title: "HSN Code 6704 — Wigs, false beards, eyebrows of human/animal hair", keywords: "wigs, false, beards, eyebrows, human, feathers & artificial flowers" },
  "6801": { title: "HSN Code 6801 — Setts, curbstones, flagstones of natural stone", keywords: "setts, curbstones, flagstones, natural, stone, stone & cement" },
  "6802": { title: "HSN Code 6802 — Worked monumental stone, marble, granite", keywords: "worked, monumental, stone, marble, granite, construction" },
  "6806": { title: "HSN Code 6806 — Mineral wool, slag wool thermal insulation", keywords: "mineral, wool, slag, wool, thermal, stone & cement" },
  "6809": { title: "HSN Code 6809 — Articles of plaster or compositions of plaster", keywords: "articles, plaster, compositions, plaster, stone & cement" },
  "6810": { title: "HSN Code 6810 — Cement, concrete or artificial stone articles", keywords: "cement, concrete, artificial, stone, articles, stone & cement" },
  "6813": { title: "HSN Code 6813 — Friction material for brakes, clutches", keywords: "friction, material, brakes, clutches, stone & cement" },
  "6901": { title: "HSN Code 6901 — Bricks, blocks, tiles of siliceous earth", keywords: "bricks, blocks, tiles, siliceous, earth, ceramics" },
  "6902": { title: "HSN Code 6902 — Refractory bricks, blocks, tiles", keywords: "refractory, bricks, blocks, tiles, ceramics" },
  "6904": { title: "HSN Code 6904 — Ceramic building bricks, flooring blocks", keywords: "ceramic, building, bricks, flooring, blocks, ceramics" },
  "6905": { title: "HSN Code 6905 — Roofing tiles, chimney pots of ceramics", keywords: "roofing, tiles, chimney, pots, ceramics" },
  "6906": { title: "HSN Code 6906 — Ceramic pipes, conduits, guttering", keywords: "ceramic, pipes, conduits, guttering, ceramics" },
  "6907": { title: "HSN Code 6907 — Ceramic Tiles", keywords: "ceramic tile, floor tile, wall tile, vitrified tile" },
  "6910": { title: "HSN Code 6910 — Ceramic sinks, wash basins, baths, toilets", keywords: "ceramic, sinks, wash, basins, baths, construction" },
  "6911": { title: "HSN Code 6911 — Tableware, kitchenware of porcelain", keywords: "tableware, kitchenware, porcelain, household" },
  "6912": { title: "HSN Code 6912 — Ceramic tableware, kitchenware", keywords: "ceramic, tableware, kitchenware, non-porcelain, ceramics" },
  "6913": { title: "HSN Code 6913 — Ceramic statuettes and ornamental articles", keywords: "ceramic, statuettes, ornamental, articles, ceramics" },
  "7005": { title: "HSN Code 7005 — Float glass, polished glass in sheets", keywords: "float, glass, polished, glass, sheets, construction" },
  "7007": { title: "HSN Code 7007 — Safety glass", keywords: "safety, glass, toughened, tempered, laminated" },
  "7009": { title: "HSN Code 7009 — Glass mirrors, framed or unframed", keywords: "glass, mirrors, framed, unframed" },
  "7010": { title: "HSN Code 7010 — Glass carboys, bottles, jars, phials, ampoules", keywords: "glass, carboys, bottles, jars, phials" },
  "7013": { title: "HSN Code 7013 — Glassware for table, kitchen use", keywords: "glassware, table, kitchen, use, household" },
  "7016": { title: "HSN Code 7016 — Glass paving blocks, bricks for building", keywords: "glass, paving, blocks, bricks, building" },
  "7017": { title: "HSN Code 7017 — Laboratory, hygienic, pharmaceutical glassware", keywords: "laboratory, hygienic, pharmaceutical, glassware, glass" },
  "7019": { title: "HSN Code 7019 — Glass fibres, rovings, yarn, mats, fabrics", keywords: "glass, fibres, rovings, yarn, mats" },
  "7101": { title: "HSN Code 7101 — Pearls, natural or cultured", keywords: "pearls, natural, cultured, precious metals & stones" },
  "7102": { title: "HSN Code 7102 — Diamonds, worked or unworked", keywords: "diamonds, worked, unworked, precious metals & stones" },
  "7103": { title: "HSN Code 7103 — Precious stones", keywords: "precious, stones, rubies, sapphires, emeralds, precious metals & stones" },
  "7104": { title: "HSN Code 7104 — Synthetic or reconstructed precious stones", keywords: "synthetic, reconstructed, precious, stones, precious metals & stones" },
  "7106": { title: "HSN Code 7106 — Silver, unwrought or semi-manufactured", keywords: "silver, unwrought, semi-manufactured, precious metals & stones" },
  "7108": { title: "HSN Code 7108 — Gold, unwrought or semi-manufactured", keywords: "gold, unwrought, semi-manufactured, precious metals & stones" },
  "7110": { title: "HSN Code 7110 — Platinum, unwrought or semi-manufactured", keywords: "platinum, unwrought, semi-manufactured, precious metals & stones" },
  "7113": { title: "HSN Code 7113 — Gold & Silver Jewellery", keywords: "gold jewellery, silver jewellery, precious metal" },
  "7114": { title: "HSN Code 7114 — Articles of goldsmiths' or silversmiths' wares", keywords: "articles, goldsmiths', silversmiths', wares, jewellery" },
  "7115": { title: "HSN Code 7115 — Articles of precious metal", keywords: "articles, precious, metal, wire, foil, precious metals & stones" },
  "7117": { title: "HSN Code 7117 — Imitation jewellery", keywords: "imitation, jewellery" },
  "7118": { title: "HSN Code 7118 — Coin, including legal tender", keywords: "coin, legal, tender, precious metals & stones" },
  "7201": { title: "HSN Code 7201 — Pig iron and spiegeleisen, ingots", keywords: "pig, iron, spiegeleisen, ingots, iron & steel" },
  "7202": { title: "HSN Code 7202 — Ferro-alloys", keywords: "ferro-alloys, iron & steel" },
  "7204": { title: "HSN Code 7204 — Ferrous waste and scrap, remelting ingots", keywords: "ferrous, waste, scrap, remelting, ingots, iron & steel" },
  "7207": { title: "HSN Code 7207 — Semi-finished products of iron or non-alloy steel", keywords: "semi-finished, products, iron, non-alloy, steel, iron & steel" },
  "7208": { title: "HSN Code 7208 — Flat-rolled iron/steel, hot-rolled, width >=600mm", keywords: "flat-rolled, iron, steel, hot-rolled, width, iron & steel" },
  "7209": { title: "HSN Code 7209 — Flat-rolled iron/steel, cold-rolled, width >=600mm", keywords: "flat-rolled, iron, steel, cold-rolled, width, iron & steel" },
  "7210": { title: "HSN Code 7210 — Steel Sheets (Hot/Cold Rolled)", keywords: "steel sheet, galvanized steel, HR coil, CR coil" },
  "7211": { title: "HSN Code 7211 — Flat-rolled iron/steel, width <600mm", keywords: "flat-rolled, iron, steel, width, <600mm, iron & steel" },
  "7212": { title: "HSN Code 7212 — Flat-rolled iron/steel, plated or coated", keywords: "flat-rolled, iron, steel, plated, coated, iron & steel" },
  "7213": { title: "HSN Code 7213 — Hot-rolled bars and rods of iron or steel", keywords: "hot-rolled, bars, rods, iron, steel, metals" },
  "7214": { title: "HSN Code 7214 — Iron & Steel Bars and Rods", keywords: "TMT bar, steel rod, iron rod, rebar, construction steel" },
  "7215": { title: "HSN Code 7215 — Bars and rods of iron/steel, cold-formed", keywords: "bars, rods, iron, steel, cold-formed, iron & steel" },
  "7216": { title: "HSN Code 7216 — Angles, shapes, sections of iron/steel", keywords: "angles, shapes, sections, iron, steel, iron & steel" },
  "7217": { title: "HSN Code 7217 — Wire of iron or non-alloy steel", keywords: "wire, iron, non-alloy, steel, iron & steel" },
  "7219": { title: "HSN Code 7219 — Stainless steel flat-rolled, width >=600mm", keywords: "stainless, steel, flat-rolled, width, >=600mm, iron & steel" },
  "7222": { title: "HSN Code 7222 — Stainless steel bars, rods, angles, shapes", keywords: "stainless, steel, bars, rods, angles, iron & steel" },
  "7225": { title: "HSN Code 7225 — Flat-rolled products of alloy steel, width >=600mm", keywords: "flat-rolled, products, alloy, steel, width, iron & steel" },
  "7228": { title: "HSN Code 7228 — Bars, rods of other alloy steel", keywords: "bars, rods, alloy, steel, iron & steel" },
  "7301": { title: "HSN Code 7301 — Sheet piling of iron or steel", keywords: "sheet, piling, iron, steel, iron & steel" },
  "7304": { title: "HSN Code 7304 — Seamless tubes and pipes of iron/steel", keywords: "seamless, tubes, pipes, iron, steel, iron & steel" },
  "7305": { title: "HSN Code 7305 — Other tubes, pipes, welded, >406mm dia", keywords: "tubes, pipes, welded, >406mm, dia, iron & steel" },
  "7306": { title: "HSN Code 7306 — Steel tubes, pipes, hollow profiles", keywords: "steel, tubes, pipes, hollow, profiles, metals" },
  "7307": { title: "HSN Code 7307 — Tube or pipe fittings of iron/steel", keywords: "tube, pipe, fittings, iron, steel, iron & steel" },
  "7308": { title: "HSN Code 7308 — Structures and parts of iron or steel", keywords: "structures, parts, iron, steel, metals" },
  "7309": { title: "HSN Code 7309 — Reservoirs, tanks, vats of iron/steel, >300L", keywords: "reservoirs, tanks, vats, iron, steel, iron & steel" },
  "7310": { title: "HSN Code 7310 — Tanks, casks, drums, boxes of iron/steel, <=300L", keywords: "tanks, casks, drums, boxes, iron, iron & steel" },
  "7311": { title: "HSN Code 7311 — Containers for compressed/liquefied gas, steel", keywords: "containers, compressed, liquefied, gas, steel, iron & steel" },
  "7312": { title: "HSN Code 7312 — Stranded wire, ropes, cables of iron/steel", keywords: "stranded, wire, ropes, cables, iron, iron & steel" },
  "7313": { title: "HSN Code 7313 — Barbed wire of iron/steel, fencing wire", keywords: "barbed, wire, iron, steel, fencing, iron & steel" },
  "7314": { title: "HSN Code 7314 — Cloth, grill, netting, fencing of iron/steel wire", keywords: "cloth, grill, netting, fencing, iron, iron & steel" },
  "7315": { title: "HSN Code 7315 — Chain and parts thereof of iron or steel", keywords: "chain, parts, thereof, iron, steel, iron & steel" },
  "7317": { title: "HSN Code 7317 — Nails, tacks, drawing pins, staples of iron/steel", keywords: "nails, tacks, drawing, pins, staples, iron & steel" },
  "7318": { title: "HSN Code 7318 — Screws, bolts, nuts, washers of iron", keywords: "screws, bolts, nuts, washers, iron, metals" },
  "7320": { title: "HSN Code 7320 — Springs and leaves for springs, of iron/steel", keywords: "springs, leaves, springs, iron, steel, iron & steel" },
  "7321": { title: "HSN Code 7321 — Stoves, cookers, grills", keywords: "stoves, cookers, grills, iron, steel, household" },
  "7322": { title: "HSN Code 7322 — Radiators and parts, air heaters of iron/steel", keywords: "radiators, parts, air, heaters, iron, iron & steel" },
  "7323": { title: "HSN Code 7323 — Table, kitchen articles of iron or steel", keywords: "table, kitchen, articles, iron, steel, household" },
  "7324": { title: "HSN Code 7324 — Sanitary ware", keywords: "sanitary, ware, sinks, baths, stainless, iron & steel" },
  "7326": { title: "HSN Code 7326 — Other articles of iron or steel", keywords: "articles, iron, steel, forgings, iron & steel" },
  "7403": { title: "HSN Code 7403 — Refined copper, unwrought, alloys", keywords: "refined, copper, unwrought, alloys" },
  "7404": { title: "HSN Code 7404 — Copper waste and scrap", keywords: "copper, waste, scrap" },
  "7407": { title: "HSN Code 7407 — Copper bars, rods and profiles", keywords: "copper, bars, rods, profiles" },
  "7408": { title: "HSN Code 7408 — Copper wire", keywords: "copper, wire" },
  "7411": { title: "HSN Code 7411 — Copper tubes and pipes", keywords: "copper, tubes, pipes" },
  "7418": { title: "HSN Code 7418 — Copper table, kitchen, sanitary ware", keywords: "copper, table, kitchen, sanitary, ware" },
  "7601": { title: "HSN Code 7601 — Unwrought aluminium", keywords: "unwrought, aluminium, alloys, ingots" },
  "7604": { title: "HSN Code 7604 — Aluminium bars, rods and profiles", keywords: "aluminium, bars, rods, profiles" },
  "7606": { title: "HSN Code 7606 — Aluminium plates, sheets, strip", keywords: "aluminium, plates, sheets, strip" },
  "7607": { title: "HSN Code 7607 — Aluminium foil, thickness <=0.2mm", keywords: "aluminium, foil, thickness, <=0.2mm" },
  "7608": { title: "HSN Code 7608 — Aluminium tubes and pipes", keywords: "aluminium, tubes, pipes" },
  "7610": { title: "HSN Code 7610 — Aluminium structures", keywords: "aluminium, structures, bridges, towers, doors" },
  "7615": { title: "HSN Code 7615 — Aluminium table, kitchen articles", keywords: "aluminium, table, kitchen, articles, household" },
  "7616": { title: "HSN Code 7616 — Other articles of aluminium", keywords: "articles, aluminium" },
  "7801": { title: "HSN Code 7801 — Unwrought lead", keywords: "unwrought, lead, other base metals" },
  "7901": { title: "HSN Code 7901 — Unwrought zinc", keywords: "unwrought, zinc, other base metals" },
  "8001": { title: "HSN Code 8001 — Unwrought tin", keywords: "unwrought, tin, other base metals" },
  "8201": { title: "HSN Code 8201 — Hand tools", keywords: "hand, tools, spades, shovels, picks, tools & cutlery" },
  "8202": { title: "HSN Code 8202 — Hand saws, blades for saws of all kinds", keywords: "hand, saws, blades, saws, all, tools & cutlery" },
  "8203": { title: "HSN Code 8203 — Files, rasps, pliers, pincers, tweezers, shears", keywords: "files, rasps, pliers, pincers, tweezers, tools & cutlery" },
  "8204": { title: "HSN Code 8204 — Hand-operated spanners and wrenches", keywords: "hand-operated, spanners, wrenches, tools & cutlery" },
  "8205": { title: "HSN Code 8205 — Other hand tools", keywords: "hand, tools, anvils, vices, blow, tools & cutlery" },
  "8207": { title: "HSN Code 8207 — Interchangeable tools for drilling, boring, milling", keywords: "interchangeable, tools, drilling, boring, milling, tools & cutlery" },
  "8211": { title: "HSN Code 8211 — Knives with cutting blades, table/pocket knives", keywords: "knives, cutting, blades, table, pocket, tools & cutlery" },
  "8212": { title: "HSN Code 8212 — Razors and razor blades", keywords: "razors, razor, blades, tools & cutlery" },
  "8213": { title: "HSN Code 8213 — Scissors, tailors' shears, and blades", keywords: "scissors, tailors', shears, blades, tools & cutlery" },
  "8215": { title: "HSN Code 8215 — Spoons, forks, ladles, skimmers, cake-servers", keywords: "spoons, forks, ladles, skimmers, cake-servers, tools & cutlery" },
  "8301": { title: "HSN Code 8301 — Padlocks, locks", keywords: "padlocks, locks, key, combination, base metal articles" },
  "8302": { title: "HSN Code 8302 — Base metal mountings, fittings", keywords: "base, metal, mountings, fittings, hinges, base metal articles" },
  "8303": { title: "HSN Code 8303 — Armoured safes, strongboxes, vault doors", keywords: "armoured, safes, strongboxes, vault, doors, base metal articles" },
  "8305": { title: "HSN Code 8305 — Staples in strips, letter clips of base metal", keywords: "staples, strips, letter, clips, base, base metal articles" },
  "8306": { title: "HSN Code 8306 — Bells, gongs, statuettes, trophies of base metal", keywords: "bells, gongs, statuettes, trophies, base, base metal articles" },
  "8309": { title: "HSN Code 8309 — Stoppers, caps, lids, seals of base metal", keywords: "stoppers, caps, lids, seals, base, base metal articles" },
  "8311": { title: "HSN Code 8311 — Wire, rods, electrodes for soldering/welding", keywords: "wire, rods, electrodes, soldering, welding, base metal articles" },
  "8402": { title: "HSN Code 8402 — Steam or other vapour generating boilers", keywords: "steam, vapour, generating, boilers, machinery" },
  "8407": { title: "HSN Code 8407 — Spark-ignition internal combustion engines", keywords: "spark-ignition, internal, combustion, engines, machinery" },
  "8408": { title: "HSN Code 8408 — Compression-ignition diesel/semi-diesel engines", keywords: "compression-ignition, diesel, semi-diesel, engines, machinery" },
  "8409": { title: "HSN Code 8409 — Parts for spark-ignition/diesel engines", keywords: "parts, spark-ignition, diesel, engines, machinery" },
  "8411": { title: "HSN Code 8411 — Turbo-jets, turbo-propellers, gas turbines", keywords: "turbo-jets, turbo-propellers, gas, turbines, machinery" },
  "8413": { title: "HSN Code 8413 — Pumps for liquids, liquid elevators", keywords: "pumps, liquids, liquid, elevators, machinery" },
  "8414": { title: "HSN Code 8414 — Air pumps, vacuum pumps, compressors, fans", keywords: "air, pumps, vacuum, pumps, compressors, machinery" },
  "8415": { title: "HSN Code 8415 — Air Conditioning Machines", keywords: "air conditioner, AC, split AC, window AC" },
  "8418": { title: "HSN Code 8418 — Refrigerators & Freezers", keywords: "refrigerator, fridge, freezer, deep freezer" },
  "8419": { title: "HSN Code 8419 — Machinery for heat treatment", keywords: "machinery, heat, treatment, pasteurisers, dryers" },
  "8421": { title: "HSN Code 8421 — Centrifuges, filters, water purifiers", keywords: "centrifuges, filters, water, purifiers, machinery" },
  "8422": { title: "HSN Code 8422 — Dish washing machines", keywords: "dish, washing, machines, appliances" },
  "8423": { title: "HSN Code 8423 — Weighing machinery, weights for balances", keywords: "weighing, machinery, weights, balances" },
  "8424": { title: "HSN Code 8424 — Mechanical spraying apparatus, fire extinguishers", keywords: "mechanical, spraying, apparatus, fire, extinguishers, machinery" },
  "8426": { title: "HSN Code 8426 — Ships' derricks, cranes, mobile lifting frames", keywords: "ships', derricks, cranes, mobile, lifting, machinery" },
  "8427": { title: "HSN Code 8427 — Fork-lift trucks, works trucks with lifting gear", keywords: "fork-lift, trucks, works, trucks, lifting, machinery" },
  "8429": { title: "HSN Code 8429 — Self-propelled bulldozers, excavators, graders", keywords: "self-propelled, bulldozers, excavators, graders, machinery" },
  "8432": { title: "HSN Code 8432 — Agricultural machinery", keywords: "agricultural, machinery, ploughs, harrows, seeders" },
  "8433": { title: "HSN Code 8433 — Harvesting, threshing machinery, mowers", keywords: "harvesting, threshing, machinery, mowers" },
  "8436": { title: "HSN Code 8436 — Other agricultural/horticultural/poultry machinery", keywords: "agricultural, horticultural, poultry, machinery" },
  "8437": { title: "HSN Code 8437 — Machines for cleaning, sorting seed/grain, milling", keywords: "machines, cleaning, sorting, seed, grain, machinery" },
  "8438": { title: "HSN Code 8438 — Food/drink industry machinery, sugar manufacture", keywords: "food, drink, industry, machinery, sugar" },
  "8443": { title: "HSN Code 8443 — Printers & Copiers", keywords: "printer, copier, printing machine, scanner" },
  "8446": { title: "HSN Code 8446 — Weaving machines, looms", keywords: "weaving, machines, looms, machinery" },
  "8450": { title: "HSN Code 8450 — Washing Machines", keywords: "washing machine, laundry machine, washer" },
  "8452": { title: "HSN Code 8452 — Sewing machines", keywords: "sewing, machines, machinery" },
  "8462": { title: "HSN Code 8462 — Machine tools for forging, stamping, pressing metal", keywords: "machine, tools, forging, stamping, pressing, machinery" },
  "8465": { title: "HSN Code 8465 — Machine tools for working wood, cork, bone", keywords: "machine, tools, working, wood, cork, machinery" },
  "8467": { title: "HSN Code 8467 — Pneumatic hand tools", keywords: "pneumatic, hand, tools, rotary, percussive, machinery" },
  "8471": { title: "HSN Code 8471 — Computers & Data Processing Machines", keywords: "computer, laptop, desktop, server" },
  "8473": { title: "HSN Code 8473 — Parts and accessories for computers", keywords: "parts, accessories, computers, electronics" },
  "8474": { title: "HSN Code 8474 — Machinery for sorting, screening, crushing, mixing", keywords: "machinery, sorting, screening, crushing, mixing" },
  "8477": { title: "HSN Code 8477 — Machinery for working rubber or plastics", keywords: "machinery, working, rubber, plastics" },
  "8479": { title: "HSN Code 8479 — Machines with individual functions", keywords: "machines, individual, functions, presses, mixers, machinery" },
  "8481": { title: "HSN Code 8481 — Taps, cocks, valves for pipes, tanks, boilers", keywords: "taps, cocks, valves, pipes, tanks, machinery" },
  "8482": { title: "HSN Code 8482 — Ball or roller bearings", keywords: "ball, roller, bearings, machinery" },
  "8483": { title: "HSN Code 8483 — Transmission shafts, cranks, bearing housings, gears", keywords: "transmission, shafts, cranks, bearing, housings, machinery" },
  "8501": { title: "HSN Code 8501 — Electric motors and generators", keywords: "electric, motors, generators, electronics" },
  "8502": { title: "HSN Code 8502 — Electric generating sets and rotary converters", keywords: "electric, generating, sets, rotary, converters, electrical" },
  "8503": { title: "HSN Code 8503 — Parts for electric motors, generators", keywords: "parts, electric, motors, generators, electrical" },
  "8504": { title: "HSN Code 8504 — Transformers, UPS & Converters", keywords: "transformer, UPS, inverter, voltage stabilizer" },
  "8505": { title: "HSN Code 8505 — Electro-magnets, electromagnetic chucks, brakes", keywords: "electro-magnets, electromagnetic, chucks, brakes, electrical" },
  "8506": { title: "HSN Code 8506 — Primary cells and batteries", keywords: "primary, cells, batteries, electronics" },
  "8507": { title: "HSN Code 8507 — Lithium-Ion Batteries", keywords: "battery, lithium ion, electric accumulator, power bank" },
  "8508": { title: "HSN Code 8508 — Vacuum cleaners, including dry and wet types", keywords: "vacuum, cleaners, dry, wet, types, electrical" },
  "8509": { title: "HSN Code 8509 — Electromechanical domestic appliances", keywords: "electromechanical, domestic, appliances, mixers, grinders, electrical" },
  "8510": { title: "HSN Code 8510 — Electric shavers, hair clippers, hair removers", keywords: "electric, shavers, hair, clippers, hair, electrical" },
  "8511": { title: "HSN Code 8511 — Electrical ignition/starting equipment for engines", keywords: "electrical, ignition, starting, equipment, engines" },
  "8512": { title: "HSN Code 8512 — Electrical lighting/signalling for vehicles, wipers", keywords: "electrical, lighting, signalling, vehicles, wipers" },
  "8513": { title: "HSN Code 8513 — Portable electric lamps", keywords: "portable, electric, lamps, torches, lanterns, electrical" },
  "8515": { title: "HSN Code 8515 — Electric brazing/soldering/welding machines", keywords: "electric, brazing, soldering, welding, machines, electrical" },
  "8516": { title: "HSN Code 8516 — Electric Heaters, Irons & Dryers", keywords: "water heater, geyser, iron box, hair dryer, toaster" },
  "8517": { title: "HSN Code 8517 — Telephone Sets & Smartphones", keywords: "mobile phone, smartphone, telephone, handset" },
  "8518": { title: "HSN Code 8518 — Microphones, speakers, headphones", keywords: "microphones, speakers, headphones, electronics" },
  "8519": { title: "HSN Code 8519 — Sound recording or reproducing apparatus", keywords: "sound, recording, reproducing, apparatus, electrical" },
  "8521": { title: "HSN Code 8521 — Video recording or reproducing apparatus", keywords: "video, recording, reproducing, apparatus, electronics" },
  "8523": { title: "HSN Code 8523 — Discs, tapes, solid-state storage devices", keywords: "discs, tapes, solid-state, storage, devices, electronics" },
  "8525": { title: "HSN Code 8525 — Transmission apparatus; cameras, camcorders", keywords: "transmission, apparatus;, cameras, camcorders, electronics" },
  "8526": { title: "HSN Code 8526 — Radar apparatus, radio navigational aid apparatus", keywords: "radar, apparatus, radio, navigational, aid, electrical" },
  "8527": { title: "HSN Code 8527 — Radio broadcast receivers", keywords: "radio, broadcast, receivers, electrical" },
  "8528": { title: "HSN Code 8528 — Monitors, Projectors & Televisions", keywords: "television, TV, monitor, projector, display" },
  "8529": { title: "HSN Code 8529 — Parts for television, radio receivers/transmitters", keywords: "parts, television, radio, receivers, transmitters, electrical" },
  "8531": { title: "HSN Code 8531 — Electric sound or visual signalling apparatus", keywords: "electric, sound, visual, signalling, apparatus, electrical" },
  "8532": { title: "HSN Code 8532 — Electrical capacitors, fixed, variable, adjustable", keywords: "electrical, capacitors, fixed, variable, adjustable" },
  "8534": { title: "HSN Code 8534 — Printed circuits", keywords: "printed, circuits, pcbs, electronics" },
  "8535": { title: "HSN Code 8535 — Electrical apparatus for switching, >1000V", keywords: "electrical, apparatus, switching, >1000v" },
  "8536": { title: "HSN Code 8536 — Electrical switches, fuses, connectors", keywords: "electrical, switches, fuses, connectors, electronics" },
  "8537": { title: "HSN Code 8537 — Boards, panels, consoles for electric control", keywords: "boards, panels, consoles, electric, control, electrical" },
  "8539": { title: "HSN Code 8539 — Electric filament or LED lamps", keywords: "electric, filament, led, lamps, electronics" },
  "8541": { title: "HSN Code 8541 — Semiconductor devices; LEDs; solar cells", keywords: "semiconductor, devices;, leds;, solar, cells, electronics" },
  "8542": { title: "HSN Code 8542 — Electronic integrated circuits and microassemblies", keywords: "electronic, integrated, circuits, microassemblies, electrical" },
  "8544": { title: "HSN Code 8544 — Insulated Wire & Cable", keywords: "wire, cable, electrical cable, optical fibre" },
  "8601": { title: "HSN Code 8601 — Rail locomotives powered by electric current", keywords: "rail, locomotives, powered, electric, current, railway" },
  "8603": { title: "HSN Code 8603 — Self-propelled railway/tramway coaches", keywords: "self-propelled, railway, tramway, coaches" },
  "8605": { title: "HSN Code 8605 — Railway passenger coaches, luggage/mail vans", keywords: "railway, passenger, coaches, luggage, mail" },
  "8606": { title: "HSN Code 8606 — Railway freight wagons", keywords: "railway, freight, wagons, tank, hopper" },
  "8607": { title: "HSN Code 8607 — Parts of railway locomotives or rolling stock", keywords: "parts, railway, locomotives, rolling, stock" },
  "8608": { title: "HSN Code 8608 — Railway track fixtures", keywords: "railway, track, fixtures, rails, sleepers" },
  "8609": { title: "HSN Code 8609 — Containers designed for transport by multiple modes", keywords: "containers, designed, transport, multiple, modes, railway" },
  "8701": { title: "HSN Code 8701 — Tractors", keywords: "tractors, agricultural, road, industrial, vehicles" },
  "8702": { title: "HSN Code 8702 — Motor vehicles for 10+ persons, buses", keywords: "motor, vehicles, 10+, persons, buses" },
  "8703": { title: "HSN Code 8703 — Motor Cars & Vehicles", keywords: "car, SUV, sedan, motor vehicle, automobile" },
  "8704": { title: "HSN Code 8704 — Motor vehicles for transport of goods", keywords: "motor, vehicles, transport, goods, trucks" },
  "8706": { title: "HSN Code 8706 — Chassis fitted with engines for motor vehicles", keywords: "chassis, fitted, engines, motor, vehicles" },
  "8707": { title: "HSN Code 8707 — Bodies including cabs for motor vehicles", keywords: "bodies, cabs, motor, vehicles" },
  "8708": { title: "HSN Code 8708 — Parts and accessories of motor vehicles", keywords: "parts, accessories, motor, vehicles" },
  "8711": { title: "HSN Code 8711 — Motorcycles & Scooters", keywords: "motorcycle, scooter, bike, two-wheeler" },
  "8712": { title: "HSN Code 8712 — Bicycles", keywords: "bicycle, cycle, non-motorized cycle" },
  "8713": { title: "HSN Code 8713 — Wheelchairs, whether or not motorised", keywords: "wheelchairs, motorised, vehicles" },
  "8714": { title: "HSN Code 8714 — Parts and accessories for motorcycles and bicycles", keywords: "parts, accessories, motorcycles, bicycles, automobiles" },
  "8716": { title: "HSN Code 8716 — Trailers, semi-trailers, non-mechanical vehicles", keywords: "trailers, semi-trailers, non-mechanical, vehicles" },
  "8801": { title: "HSN Code 8801 — Balloons, dirigibles, gliders, hang gliders, kites", keywords: "balloons, dirigibles, gliders, hang, gliders, aircraft" },
  "8802": { title: "HSN Code 8802 — Aeroplanes, helicopters, spacecraft, satellites", keywords: "aeroplanes, helicopters, spacecraft, satellites, aircraft" },
  "8803": { title: "HSN Code 8803 — Parts of balloons, aircraft, helicopters, spacecraft", keywords: "parts, balloons, aircraft, helicopters, spacecraft" },
  "8804": { title: "HSN Code 8804 — Parachutes and rotochutes, parts and accessories", keywords: "parachutes, rotochutes, parts, accessories, aircraft" },
  "8901": { title: "HSN Code 8901 — Cruise ships, cargo vessels, barges", keywords: "cruise, ships, cargo, vessels, barges" },
  "8902": { title: "HSN Code 8902 — Fishing vessels, factory ships", keywords: "fishing, vessels, factory, ships" },
  "8903": { title: "HSN Code 8903 — Yachts and other pleasure or sports boats", keywords: "yachts, pleasure, sports, boats, ships" },
  "8904": { title: "HSN Code 8904 — Tugs and pusher craft", keywords: "tugs, pusher, craft, ships" },
  "8905": { title: "HSN Code 8905 — Light-vessels, dredgers, floating docks/cranes", keywords: "light-vessels, dredgers, floating, docks, cranes, ships" },
  "8907": { title: "HSN Code 8907 — Floating structures", keywords: "floating, structures, rafts, pontoons, buoys, ships" },
  "9001": { title: "HSN Code 9001 — Optical fibres and cables; lenses", keywords: "optical, fibres, cables;, lenses" },
  "9002": { title: "HSN Code 9002 — Lenses, prisms, mirrors, optical elements mounted", keywords: "lenses, prisms, mirrors, optical, elements, instruments" },
  "9003": { title: "HSN Code 9003 — Frames and mountings for spectacles/goggles", keywords: "frames, mountings, spectacles, goggles, instruments" },
  "9004": { title: "HSN Code 9004 — Spectacles & Sunglasses", keywords: "spectacles, sunglasses, goggles, eyewear" },
  "9005": { title: "HSN Code 9005 — Binoculars, monoculars, telescopes", keywords: "binoculars, monoculars, telescopes, instruments" },
  "9006": { title: "HSN Code 9006 — Photographic cameras, flash apparatus", keywords: "photographic, cameras, flash, apparatus, instruments" },
  "9011": { title: "HSN Code 9011 — Compound optical microscopes", keywords: "compound, optical, microscopes, instruments" },
  "9015": { title: "HSN Code 9015 — Surveying, hydrographic, meteorological instruments", keywords: "surveying, hydrographic, meteorological, instruments" },
  "9017": { title: "HSN Code 9017 — Drawing, marking-out, mathematical instruments", keywords: "drawing, marking-out, mathematical, instruments" },
  "9018": { title: "HSN Code 9018 — Medical & Surgical Instruments", keywords: "medical instruments, surgical tools, stethoscope" },
  "9021": { title: "HSN Code 9021 — Orthopaedic appliances, hearing aids", keywords: "orthopaedic, appliances, hearing, aids, medical" },
  "9022": { title: "HSN Code 9022 — Apparatus based on X-rays, alpha, beta, gamma rays", keywords: "apparatus, based, x-rays, alpha, beta, instruments" },
  "9025": { title: "HSN Code 9025 — Hydrometers, thermometers, pyrometers", keywords: "hydrometers, thermometers, pyrometers, instruments" },
  "9026": { title: "HSN Code 9026 — Instruments for measuring flow, level, pressure", keywords: "instruments, measuring, flow, level, pressure" },
  "9027": { title: "HSN Code 9027 — Instruments for physical/chemical analysis", keywords: "instruments, physical, chemical, analysis, spectrometers" },
  "9028": { title: "HSN Code 9028 — Gas, liquid, electricity supply meters", keywords: "gas, liquid, electricity, supply, meters, instruments" },
  "9030": { title: "HSN Code 9030 — Oscilloscopes, spectrum analysers, multimeters", keywords: "oscilloscopes, spectrum, analysers, multimeters, instruments" },
  "9031": { title: "HSN Code 9031 — Measuring or checking instruments", keywords: "measuring, checking, instruments, projectors" },
  "9032": { title: "HSN Code 9032 — Automatic regulating or controlling instruments", keywords: "automatic, regulating, controlling, instruments" },
  "9101": { title: "HSN Code 9101 — Wrist-watches with case of precious metal", keywords: "wrist-watches, case, precious, metal, clocks & watches" },
  "9102": { title: "HSN Code 9102 — Wrist-watches, other than precious metal case", keywords: "wrist-watches, precious, metal, case, clocks & watches" },
  "9103": { title: "HSN Code 9103 — Clocks with watch movements", keywords: "clocks, watch, movements, clocks & watches" },
  "9105": { title: "HSN Code 9105 — Other clocks", keywords: "clocks, wall, mantel, cuckoo, alarm, clocks & watches" },
  "9111": { title: "HSN Code 9111 — Watch cases and parts of watch cases", keywords: "watch, cases, parts, watch, cases, clocks & watches" },
  "9113": { title: "HSN Code 9113 — Watch straps, bands and bracelets", keywords: "watch, straps, bands, bracelets, clocks & watches" },
  "9201": { title: "HSN Code 9201 — Pianos, including automatic, harpsichords", keywords: "pianos, automatic, harpsichords, musical instruments" },
  "9202": { title: "HSN Code 9202 — String instruments", keywords: "string, instruments, guitars, violins, harps, musical instruments" },
  "9205": { title: "HSN Code 9205 — Wind instruments", keywords: "wind, instruments, clarinets, trumpets, flutes, musical instruments" },
  "9206": { title: "HSN Code 9206 — Percussion instruments", keywords: "percussion, instruments, drums, xylophones, cymbals, musical instruments" },
  "9207": { title: "HSN Code 9207 — Musical instruments, sound produced electrically", keywords: "musical, instruments, sound, produced, electrically, musical instruments" },
  "9209": { title: "HSN Code 9209 — Parts and accessories of musical instruments", keywords: "parts, accessories, musical, instruments, musical instruments" },
  "9301": { title: "HSN Code 9301 — Military weapons, other than revolvers/pistols", keywords: "military, weapons, revolvers, pistols, arms & ammunition" },
  "9303": { title: "HSN Code 9303 — Other firearms", keywords: "firearms, shotguns, rifles, arms & ammunition" },
  "9304": { title: "HSN Code 9304 — Air guns, spring guns, truncheons", keywords: "air, guns, spring, guns, truncheons, arms & ammunition" },
  "9306": { title: "HSN Code 9306 — Bombs, grenades, ammunition, cartridges, pellets", keywords: "bombs, grenades, ammunition, cartridges, pellets, arms & ammunition" },
  "9401": { title: "HSN Code 9401 — Seats, Chairs & Sofas", keywords: "chair, sofa, seat, office chair, furniture" },
  "9402": { title: "HSN Code 9402 — Medical, surgical, dental, veterinary furniture", keywords: "medical, surgical, dental, veterinary, furniture" },
  "9403": { title: "HSN Code 9403 — Furniture (Tables, Desks, Wardrobes)", keywords: "table, desk, wardrobe, furniture, bookshelf" },
  "9404": { title: "HSN Code 9404 — Mattress supports; mattresses", keywords: "mattress, supports;, mattresses, furniture" },
  "9405": { title: "HSN Code 9405 — Lamps and lighting fittings", keywords: "lamps, lighting, fittings, furniture" },
  "9406": { title: "HSN Code 9406 — Prefabricated buildings", keywords: "prefabricated, buildings, furniture" },
  "9503": { title: "HSN Code 9503 — Toys, Dolls & Games", keywords: "toys, dolls, games, tricycle, toy cars" },
  "9504": { title: "HSN Code 9504 — Video game consoles, carrom boards, chess", keywords: "video, game, consoles, carrom, boards, toys" },
  "9505": { title: "HSN Code 9505 — Festive, carnival, entertainment articles", keywords: "festive, carnival, entertainment, articles, toys & games" },
  "9506": { title: "HSN Code 9506 — Sports equipment, gym articles", keywords: "sports, equipment, gym, articles" },
  "9507": { title: "HSN Code 9507 — Fishing rods, tackle, landing nets", keywords: "fishing, rods, tackle, landing, nets, toys & games" },
  "9601": { title: "HSN Code 9601 — Worked ivory, bone, horn, coral, shell", keywords: "worked, ivory, bone, horn, coral, miscellaneous" },
  "9603": { title: "HSN Code 9603 — Brooms, brushes, squeegees, mops, feather dusters", keywords: "brooms, brushes, squeegees, mops, feather, miscellaneous" },
  "9606": { title: "HSN Code 9606 — Buttons, press-fasteners, snap-fasteners", keywords: "buttons, press-fasteners, snap-fasteners, miscellaneous" },
  "9607": { title: "HSN Code 9607 — Slide fasteners, zippers, and parts thereof", keywords: "slide, fasteners, zippers, parts, thereof, miscellaneous" },
  "9608": { title: "HSN Code 9608 — Ball point pens, felt tipped pens", keywords: "ball, point, pens, felt, tipped, stationery" },
  "9609": { title: "HSN Code 9609 — Pencils, crayons, chalk", keywords: "pencils, crayons, chalk, stationery" },
  "9611": { title: "HSN Code 9611 — Date, sealing, numbering stamps", keywords: "date, sealing, numbering, stamps, miscellaneous" },
  "9613": { title: "HSN Code 9613 — Cigarette lighters and other lighters", keywords: "cigarette, lighters, lighters, miscellaneous" },
  "9615": { title: "HSN Code 9615 — Combs, hair-slides, hairpins, curling pins", keywords: "combs, hair-slides, hairpins, curling, pins, miscellaneous" },
  "9617": { title: "HSN Code 9617 — Vacuum flasks, thermos, parts", keywords: "vacuum, flasks, thermos, parts, miscellaneous" },
  "9619": { title: "HSN Code 9619 — Sanitary towels, napkins, diapers", keywords: "sanitary, towels, napkins, diapers, health" },
  "9954": { title: "SAC Code 9954 — Construction services", keywords: "construction, services" },
  "9961": { title: "SAC Code 9961 — Financial and insurance services", keywords: "financial, insurance, services" },
  "9962": { title: "SAC Code 9962 — Financial and related services", keywords: "financial, related, services, banking, lending" },
  "9963": { title: "SAC Code 9963 — Leasing or rental services", keywords: "leasing, rental, services" },
  "9964": { title: "SAC Code 9964 — Passenger Transport Services", keywords: "cab, taxi, bus, passenger transport, ride" },
  "9965": { title: "SAC Code 9965 — Goods transport services", keywords: "goods, transport, services" },
  "9966": { title: "SAC Code 9966 — Rental services of transport vehicles", keywords: "rental, services, transport, vehicles" },
  "9967": { title: "SAC Code 9967 — Cargo handling, warehousing and storage services", keywords: "cargo, handling, warehousing, storage, services" },
  "9968": { title: "SAC Code 9968 — Postal and courier services", keywords: "postal, courier, services" },
  "9969": { title: "SAC Code 9969 — Electricity, gas and water distribution services", keywords: "electricity, gas, water, distribution, services" },
  "9970": { title: "SAC Code 9970 — Environmental protection services", keywords: "environmental, protection, services" },
  "9971": { title: "SAC Code 9971 — Financial intermediation and related services", keywords: "financial, intermediation, related, services" },
  "9972": { title: "SAC Code 9972 — Real estate services", keywords: "real, estate, services" },
  "9973": { title: "SAC Code 9973 — Leasing / rental without operator", keywords: "leasing, rental, without, operator, services" },
  "9974": { title: "SAC Code 9974 — Accommodation, food and beverage services", keywords: "accommodation, food, beverage, services" },
  "9975": { title: "SAC Code 9975 — Public healthcare and residential care services", keywords: "public, healthcare, residential, care, services" },
  "9976": { title: "SAC Code 9976 — Government social security and welfare services", keywords: "government, social, security, welfare, services" },
  "9977": { title: "SAC Code 9977 — Community, social and personal services", keywords: "community, social, personal, services" },
  "9978": { title: "SAC Code 9978 — Printing, publishing and reproduction services", keywords: "printing, publishing, reproduction, services" },
  "9979": { title: "SAC Code 9979 — Entertainment, amusement and recreation services", keywords: "entertainment, amusement, recreation, services" },
  "9980": { title: "SAC Code 9980 — Domestic services", keywords: "domestic, services, cooks, drivers, maids" },
  "9981": { title: "SAC Code 9981 — Research and development services", keywords: "research, development, services" },
  "9982": { title: "SAC Code 9982 — Legal and accounting services", keywords: "legal, accounting, services" },
  "9983": { title: "SAC Code 9983 — IT, Consulting & Professional Services", keywords: "IT services, consulting, software services, web development" },
  "9984": { title: "SAC Code 9984 — Telecommunications, broadcasting services", keywords: "telecommunications, broadcasting, services" },
  "9985": { title: "SAC Code 9985 — Support services", keywords: "support, services, security, cleaning, temp" },
  "9986": { title: "SAC Code 9986 — Support services to agriculture, forestry", keywords: "support, services, agriculture, forestry" },
  "9987": { title: "SAC Code 9987 — Maintenance and repair services", keywords: "maintenance, repair, services" },
  "9988": { title: "SAC Code 9988 — Manufacturing services on physical inputs", keywords: "manufacturing, services, physical, inputs" },
  "9989": { title: "SAC Code 9989 — Other manufacturing services, sub-contracting", keywords: "manufacturing, services, sub-contracting" },
  "9990": { title: "SAC Code 9990 — Services of charitable/religious organisations", keywords: "services, charitable, religious, organisations" },
  "9991": { title: "SAC Code 9991 — Public administration services", keywords: "public, administration, services" },
  "9992": { title: "SAC Code 9992 — Education services", keywords: "education, services" },
  "9993": { title: "SAC Code 9993 — Health and social care services", keywords: "health, social, care, services" },
  "9994": { title: "SAC Code 9994 — Sewage and waste collection, treatment, disposal", keywords: "sewage, waste, collection, treatment, disposal, services" },
  "9995": { title: "SAC Code 9995 — Services of membership organisations", keywords: "services, membership, organisations" },
  "9996": { title: "SAC Code 9996 — Recreational, cultural and sporting services", keywords: "recreational, cultural, sporting, services" },
  "9997": { title: "SAC Code 9997 — Other services", keywords: "services, laundry, beauty, wellness, funeral" },
  "9998": { title: "SAC Code 9998 — Employment services, manpower supply", keywords: "employment, services, manpower, supply" },
};

function exampleCalc(rate) {
  if (rate === 0) return null;
  const base = 10000;
  const tax = (base * rate) / 100;
  return { base, tax, total: base + tax };
}

export default function HsnCodePage() {
  const { code } = useParams();
  const hsn = getByCode(code);
  const meta = TOP_HSN_META[code];

  // Before the not-found return, not after it: a hook below an early return
  // runs on some renders and not others, and moving between an unknown and a
  // known code on this route changed the hook count — React's "Rendered more
  // hooks than during the previous render", and a blank page.
  const pageTitle = hsn
    ? `${meta?.title || `${hsn.sac ? "SAC" : "HSN"} Code ${hsn.code} — ${hsn.desc}`} | GST Rate ${hsn.rate}%`
    : `HSN Code ${code} Not Found`;
  usePageTitle(pageTitle);

  if (!hsn) {
    return (
      <div className="tool-page">
        <ToolsNav />
        <main className="tool-main">
          <div className="tool-container">
            <h1 className="tool-title">HSN Code Not Found</h1>
            <p>The HSN code &ldquo;{code}&rdquo; was not found in our database.</p>
            <p><Link to="/hsn">Search all HSN codes →</Link></p>
          </div>
        </main>
        <DoAideFooter />
      </div>
    );
  }

  const isSac = hsn.sac;
  const codeType = isSac ? "SAC" : "HSN";

  const example = exampleCalc(hsn.rate);

  const related = searchHSN(hsn.category, { limit: 8 })
    .filter((h) => h.code !== hsn.code);

  const faqSchema = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: [
      {
        "@type": "Question",
        name: `What is ${codeType} code ${hsn.code}?`,
        acceptedAnswer: {
          "@type": "Answer",
          text: `${codeType} code ${hsn.code} covers ${hsn.desc}. It falls under the ${hsn.category} category and attracts GST at ${hsn.rate}%.`,
        },
      },
      {
        "@type": "Question",
        name: `What is the GST rate for ${codeType} code ${hsn.code}?`,
        acceptedAnswer: {
          "@type": "Answer",
          text: `The GST rate for ${codeType} code ${hsn.code} (${hsn.desc}) is ${hsn.rate}%.${hsn.rate > 0 ? ` For intra-state supply: CGST ${hsn.rate / 2}% + SGST ${hsn.rate / 2}%. For inter-state supply: IGST ${hsn.rate}%.` : ""}`,
        },
      },
    ],
  };

  const productSchema = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: pageTitle,
    url: `${BASE_URL}/hsn/${hsn.code}`,
    description: `${codeType} code ${hsn.code} — ${hsn.desc}. GST rate: ${hsn.rate}%. Category: ${hsn.category}.`,
  };

  const breadcrumbs = [
    { name: "Home", url: BASE_URL },
    { name: "HSN Finder", url: `${BASE_URL}/hsn` },
    { name: `${codeType} ${hsn.code}` },
  ];

  return (
    <div className="tool-page">
      <SeoHead
        title={`${codeType} Code ${hsn.code} — ${hsn.desc} | GST Rate ${hsn.rate}%`}
        description={`${codeType} code ${hsn.code} covers ${hsn.desc}. GST rate: ${hsn.rate}%. Category: ${hsn.category}. Find tax breakup, related codes, and GST calculation examples.`}
        path={`/hsn/${hsn.code}`}
        jsonLd={[faqSchema, productSchema]}
        breadcrumbs={breadcrumbs}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">{codeType} Code {hsn.code}</h1>
          <p className="tool-subtitle">{hsn.desc}</p>

          <div className="calc-card">
            <div className="calc-result">
              <div className="calc-result-row">
                <span>{codeType} Code</span>
                <strong>{hsn.code}</strong>
              </div>
              <div className="calc-result-row">
                <span>Description</span>
                <strong>{hsn.desc}</strong>
              </div>
              <div className="calc-result-row">
                <span>Category</span>
                <strong>{hsn.category}</strong>
              </div>
              <div className="calc-result-row calc-total">
                <span>GST Rate</span>
                <strong>{hsn.rate}%</strong>
              </div>
              {hsn.rate > 0 && (
                <>
                  <div className="calc-result-row">
                    <span>CGST + SGST (Intra-state)</span>
                    <strong>{hsn.rate / 2}% + {hsn.rate / 2}%</strong>
                  </div>
                  <div className="calc-result-row">
                    <span>IGST (Inter-state)</span>
                    <strong>{hsn.rate}%</strong>
                  </div>
                </>
              )}
            </div>

            {example && (
              <div style={{ marginTop: "1rem", padding: "0.75rem", background: "var(--bg-alt, #f5f5f5)", borderRadius: "0.5rem" }}>
                <strong>Example Calculation</strong>
                <p style={{ margin: "0.5rem 0 0", fontSize: "0.95rem" }}>
                  On a taxable value of {formatINR(example.base)}: GST = {formatINR(example.tax)}, Total = {formatINR(example.total)}
                </p>
              </div>
            )}

            <div className="calc-result-actions" style={{ marginTop: "1rem" }}>
              <ShareButtons
                path={`/hsn/${hsn.code}`}
                text={`${codeType} code ${hsn.code} — ${hsn.desc} — GST rate ${hsn.rate}%`}
              />
            </div>
          </div>

          <div style={{ margin: "1.5rem 0", display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <Link to={`/calculator?rate=${hsn.rate}`} className="btn btn-primary">
              Calculate GST at {hsn.rate}%
            </Link>
            <Link to="/hsn" className="btn compare-cta-secondary">
              Search More HSN Codes
            </Link>
          </div>

          {related.length > 0 && (
            <section className="tool-info">
              <h2>Related {codeType} Codes in {hsn.category}</h2>
              <table className="due-date-table">
                <thead>
                  <tr>
                    <th>{codeType} Code</th>
                    <th>Description</th>
                    <th>GST Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {related.map((r) => (
                    <tr key={r.code}>
                      <td><Link to={`/hsn/${r.code}`}>{r.code}</Link></td>
                      <td>{r.desc}</td>
                      <td>{r.rate}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="tool-info">
            <h2>About {codeType} Code {hsn.code}</h2>
            <p>
              {codeType} code {hsn.code} is used to classify <strong>{hsn.desc.toLowerCase()}</strong> under
              the Goods and Services Tax ({isSac ? "GST Services" : "GST"}) system in India.
              This code falls under the <strong>{hsn.category}</strong> category and attracts
              a GST rate of <strong>{hsn.rate}%</strong>.
            </p>
            {!isSac && (
              <p>
                HSN (Harmonized System of Nomenclature) is an internationally standardized system
                of names and numbers to classify traded products. Under GST, businesses with
                turnover above ₹5 crore must report 6-digit HSN codes on invoices, while those
                between ₹1.5 crore and ₹5 crore must report 4-digit codes.
              </p>
            )}
            {isSac && (
              <p>
                SAC (Services Accounting Code) is used under GST to classify services.
                All service providers must mention the SAC code on their GST invoices.
              </p>
            )}
          </section>

          <RelatedTools current={`/hsn/${hsn.code}`} />
          <CrossProductLinks page="hsn-code" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { TOP_HSN_META };
