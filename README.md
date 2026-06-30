# Transformer

A focused QGIS attribute manager for controlled vector transformations.

Transformer helps teams turn project layers into reliable data products: select the right features, calculate precise fields, validate the result, then publish to files or PostgreSQL.

## What it is

Transformer is an attribute manager, not an ETL extractor. It does not replace QGIS; it organizes QGIS expressions, filters, exports, and database publishing into a repeatable workflow.

The experience is intentionally minimal: every panel supports one decision, and every transformation remains visible through configuration and logs.

## Designed for enterprise geodata

- **Controlled inputs**: work from vector layers already present in the QGIS project
- **Precise rules**: use the native QGIS expression engine for fields, geometry, and filters
- **Repeatable outputs**: save JSON configurations and reuse them across similar layers
- **Operational visibility**: follow progress, warnings, and errors in the Activity Monitor
- **Publication path**: export to common vector formats or publish through PostgreSQL mapping

## Core workflow

### 1. Select

Choose the source layer from the QGIS project. Transformer keeps the source visible and leaves the original layer untouched.

### 2. Shape

Define the target table name, calculated fields, geometry-derived values, and data types.

### 3. Filter

Keep only the features that matter by using QGIS expressions such as:

```qgis
"TYPE" = 'Building' AND area($geometry) > 1000
```

### 4. Validate

Check expressions before running a full transformation. Use the Activity Monitor as the trace of record.

### 5. Publish

Create QGIS memory layers, export files, or map the transformed fields to PostgreSQL targets.

## Interface map

| Area | Purpose |
| --- | --- |
| **Source Files** | Select project layers and inspect available sources |
| **Configuration** | Define table structure, filters, expressions, and calculated fields |
| **Configuration Preview** | Review the JSON configuration before execution |
| **Activity Monitor** | Read progress, warnings, errors, and operational context |
| **Quick Help** | Access expression, filter, and workflow references without leaving the plugin |
| **Export** | Write transformed data to supported vector formats |
| **PostgreSQL** | Configure connection, mapping, and database publishing |

## Expression examples

### Geometry

```qgis
area($geometry)
perimeter($geometry)
centroid($geometry)
buffer($geometry, 25)
```

### Attributes

```qgis
upper("CODE")
concat("CITY", ' - ', "DISTRICT")
round("VALUE", 2)
```

### Filters

```qgis
is_valid($geometry)
"STATUS" = 'ACTIVE'
"POPULATION" BETWEEN 1000 AND 5000
"NAME" ILIKE '%central%'
```

## Configuration format

Configurations are stored as JSON so they can be reviewed, shared, and reused.

```json
{
  "version": "1.0",
  "filter": {
    "enabled": true,
    "expression": "area($geometry) > 1000 AND \"STATUS\" = 'ACTIVE'"
  },
  "fields": [
    {
      "name": "area_m2",
      "expression": "area($geometry)",
      "type": "Real"
    },
    {
      "name": "centroid_x",
      "expression": "x(centroid($geometry))",
      "type": "Real"
    }
  ],
  "target_table": "processed_data"
}
```

## Practical standards

- **Validate first**: test filters and expressions before processing large layers
- **Keep fields intentional**: publish only columns that serve the target use case
- **Prefer simple rules**: compose clear expressions instead of hidden manual cleanup
- **Use saved configurations**: make recurring transformations explicit and repeatable
- **Read the logs**: resolve warnings before PostgreSQL publishing or file delivery

## Requirements

- **QGIS**: 3.44 or higher
- **Python**: QGIS bundled Python
- **System**: Windows, macOS, or Linux
- **PostgreSQL**: optional, required only for database publishing

## Installation

1. Copy the plugin directory into the QGIS profile plugin folder.
2. Restart QGIS.
3. Enable **Transformer** from the QGIS Plugin Manager.
4. Open Transformer from the plugin toolbar or menu.

Typical profile plugin folder:

```text
<QGIS profile>/python/plugins/Transfomer
```

## Version 3.0.0

- Focused the product on attribute transformation, export, and PostgreSQL integration
- Removed unstable join and pipeline modules from the user workflow
- Updated the interface around the Configuration, Export, and PostgreSQL path
- Refined help content and Activity Monitor wording for a clearer enterprise workflow

## Support

Report issues on [GitHub Issues](https://github.com/yadda07/Transformer/issues).

When reporting an issue, include:

- QGIS version
- Transformer version
- Source layer type and feature volume
- JSON configuration, if relevant
- Activity Monitor messages related to the operation

## Project

- **Author**: Yadda
- **Website**: [geodeci.xyz](https://geodeci.xyz/)
- **Repository**: [github.com/yadda07/Transformer](https://github.com/yadda07/Transformer)
- **Issues**: [github.com/yadda07/Transformer/issues](https://github.com/yadda07/Transformer/issues)
- **Contact**: youcef.geodesien@gmail.com
- **License**: Open Source
