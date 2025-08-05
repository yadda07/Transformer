# Transformer Plugin - QGIS

A QGIS plugin for transforming vector files with calculated fields, coordinate reprojection, and export capabilities. Supports all QGIS-compatible vector formats, batch processing, and PostgreSQL database integration.

## Overview

**Transformer** is a comprehensive ETL (Extract, Transform, Load) solution built within QGIS, providing enterprise-grade data processing capabilities through integrated components that work seamlessly together. This plugin addresses the need for powerful, accessible transformation tools by leveraging QGIS's rich API ecosystem to deliver functionality comparable to commercial ETL platforms.

### ETL Integration Philosophy
The plugin combines multiple ETL components into a unified workflow: **Reader + AttributeManager + Reprojector + Writer + ConfigurationManager**, enabling complete data processing pipelines. Once configured, the entire transformation process becomes automated - users define their workflow once and execute it repeatedly with consistent results.

Supports 15+ vector formats including Shapefile, GeoJSON, GeoPackage, KML, DXF, GPX, and more. The tool emphasizes workflow automation through persistent configurations, making it ideal for organizations requiring standardized, repeatable data processing workflows.

## ETL Architecture

### Integrated Component System
Transformer provides a cohesive ETL architecture where each component is designed to work in harmony with others, creating powerful data processing pipelines:

- **Universal Reader**: Multi-format input support (15+ vector formats) with intelligent format detection
- **Advanced AttributeManager**: Complex field calculations, expressions, and data type transformations
- **Spatial Reprojector**: Coordinate system transformations and geometric operations
- **Multi-format Writer**: Flexible output options with database integration capabilities
- **Configuration Manager**: Persistent workflow templates for automation and standardization
- **Batch Processor**: Scalable processing for enterprise datasets

### Workflow Automation
Once configured, the transformation pipeline operates autonomously - eliminating manual intervention for recurring tasks. This approach transforms complex, multi-step processes into simple, one-click operations, significantly improving productivity for geospatial data workflows.

## Features

### Data Transformation

* Transform multiple vector files in batch mode (15+ formats supported)
* Apply coordinate system reprojection
* Calculate geometric properties (area, perimeter, centroid)
* Transform and map field data types

### Export Options

* Export to shapefile, GeoJSON, CSV, and other formats
* Process multiple files at once
* Maintain consistent output structure
* Configure field mapping rules

### PostgreSQL Integration

* Connect to PostgreSQL databases
* Automatic field matching between source and target
* Manual field mapping when needed
* Handle data type conversions

### Configuration

* Save transformation settings as templates
* Reuse configurations for similar tasks
* Share settings between users
* Version tracking for configuration changes

## Use Cases

This plugin can be useful for:

* Standardizing data formats across multiple shapefiles
* Creating consistent export formats for regular deliveries
* Automating repetitive transformation tasks
* Integrating with PostgreSQL databases
* Processing multiple files with the same transformation rules

The tool is suitable for organizations that need to:

* Maintain consistent export formats
* Process data regularly with similar requirements
* Work with PostgreSQL databases
* Handle multiple shapefiles with standardized outputs

## Technical Requirements

* **QGIS**: Version 3.10 or higher
* **Python**: 3.6+ (included with QGIS)
* **System**: Windows, macOS, Linux
* **PostgreSQL**: Optional, for database integration features

## Installation

### Manual Installation

1. Download the plugin files
2. Create the plugin directory in QGIS:
   ```
   ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/transformer/
   ```
3. Copy all Python files to this directory
4. Restart QGIS
5. Enable the plugin in the Extension Manager

### File Structure

```
transformer/
├── __init__.py
├── main_plugin.py
├── Transformer_dialog.py
├── gestionnaire.py
├── trans_calc.py
├── export_module.py
├── postgresql_integration.py
├── logger.py
├── styles.css
├── metadata.txt
└── readme.md
```

## Usage Guide

### 1. Plugin Access

* **Menu**: `Extensions > Shape Transformer`
* **Toolbar**: Click the plugin icon
* **Vector Menu**: `Vector > Shape Transformer`

### 2. Main Interface

The interface consists of three main panels:

#### Left Panel - Shapefile Management

* **Load Files**: "Load Shapes" button to add multiple files
* **File List**: Display loaded shapefiles with feature counts
* **Management**: Remove or refresh loaded files

#### Center Panel - Transformation Configuration

**Quick Configuration:**

* **Target Table**: Destination table name
* **Field Name**: Name for calculated fields

**Advanced Filtering:**

* **Filter Toggle**: Enable/disable data filtering
* **Filter Expression**: Custom QGIS expressions for data selection
* **Expression Builder**: Native QGIS expression builder with autocomplete
* **Filter Testing**: Real-time validation and feature count preview
* **Quick Filters**: Predefined filter buttons (Area > 100, Valid Geometry, Not NULL)

**Calculated Fields:**

* **QGIS Native Engine**: Full access to QGIS expression functions
* **Real-time Validation**: Expression syntax checking
* **Field Operations**: Area, centroid, geometry operations, and custom calculations

#### Right Panel - Configuration Preview

* **Configured Fields**: List of defined calculated fields
* **Shapefile Details**: File information and applied filters
* **JSON Preview**: Complete configuration including filters and transformations
* **Action Buttons**: Test, save, and execute transformations

### 3. Standard Workflow

#### Step 1: Load Data

```
1. Click "Load Shapes"
2. Select one or multiple .shp files
3. Files appear in the list with metadata
```

#### Step 2: Configure Filters

```
1. Select shapefile from the list
2. Check "Enable Filter"
3. Define filter expressions:
   - "TYPE" = 'Commercial'
   - area($geometry) > 1000
   - "STATUS" = 'ACTIVE' AND "VALUE" > 0
4. Click "Test Filter" to validate
```

#### Step 3: Define Calculated Fields

```
1. Open Expression Builder
2. Define expressions such as:
   - Area: area($geometry)
   - Centroid X: x(centroid($geometry))
   - Perimeter: perimeter($geometry)
   - Custom field: "FIELD1" + "_" + "FIELD2"
3. Validate each expression
4. Add field to configuration
```

#### Step 4: Export Configuration

```
1. Review configuration in JSON preview
2. Test transformation with "Test" button
3. Save configuration for reuse
4. Execute batch processing
```

#### Step 5: Database Export (PostgreSQL)

```
1. Configure database connection
2. Select target schema and table
3. Review automatic field mapping
4. Adjust mappings manually if needed
5. Execute export with data type conversion
```

### 4. Configuration Management

#### Save Configuration

```
1. Configure filters and calculated fields
2. Click "Save Config" in right panel
3. Choose JSON filename
4. Complete configuration is saved
```

#### Load Configuration

```
1. Click "Load Config"
2. Select JSON configuration file
3. All filters and calculated fields are restored
4. Apply to any compatible shapefile
```

### 5. JSON Configuration Format

Example saved configuration:

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
  "target_table": "processed_data",
  "postgresql": {
    "enabled": true,
    "schema": "public",
    "table_mapping": {
      "auto_detect": true,
      "manual_overrides": {}
    }
  }
}
```

## Best Practices

### Efficient Filtering

* **Combine conditions**: Use AND/OR for complex filters
* **Test regularly**: Validate expressions before transformation
* **Geometric filters**: area(), perimeter(), is_valid($geometry)
* **Attribute filters**: String and numeric comparisons

### Advanced Calculated Fields

* **Geometric functions**: centroid(), bounds(), buffer()
* **Mathematical functions**: round(), abs(), sqrt()
* **String functions**: concat(), upper(), lower()
* **Conditional functions**: CASE WHEN THEN ELSE

### Performance Tips

* Filter data before applying calculations to reduce processing time
* Use simple expressions when possible
* Test transformations step-by-step
* Process files in batches when handling many files

## Database Integration

### PostgreSQL Support

* Automatic field type matching between source and target
* Manual field mapping when automatic matching is not suitable
* Data type conversion handling
* Secure connection management
* Support for multiple table processing

### Export Formats

* Shapefile (ESRI format)
* CAD (DWG, DXF)
* GeoJSON
* CSV (tabular data)
* PostgreSQL (direct database export)
* Other formats supported by QGIS

## Configuration Management

### Sharing Configurations

* Save configurations as templates
* Track changes to configuration files
* Maintain consistent output formats
* Reuse settings for similar tasks

### Validation

* Expression syntax checking
* Geometry validation
* Output format verification
* Error reporting and logging

## Development Vision

### Expanding QGIS ETL Capabilities
Transformer represents the foundation of a broader vision to harness QGIS's extensive API ecosystem for comprehensive ETL solutions. QGIS provides a remarkably rich platform for geospatial data processing, and this plugin demonstrates how its capabilities can be systematically organized into enterprise-ready workflows.

### Future Development
This plugin serves as the first step toward creating more sophisticated ETL components within the QGIS environment. Future development aims to expand the toolkit with additional specialized processors, advanced workflow orchestration, and enhanced automation capabilities - all built upon QGIS's proven foundation.

The goal is to continue developing comprehensive solutions that leverage QGIS's strengths while providing the structured, repeatable workflows that enterprise environments require.

## Technical Support

**Developed by**: Yadda
**Contact**: youcef.geodesien@gmail.com
**Version**: 1.1.0
**License**: Open Source

For technical support, please include:

- QGIS version used
- Problem description
- JSON configuration file (if applicable)
- Error messages from Log Panel

## Contributing

Contributions are welcome. Please contact the development team for information about contributing to the project.
