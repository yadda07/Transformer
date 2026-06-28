# Transformer - QGIS ETL Plugin

ETL plugin for vector layer transformation in QGIS. Calculated fields, geometry expressions, smart filtering, and PostgreSQL integration.

## Overview

**Transformer** provides ETL (Extract, Transform, Load) functionality for vector data transformation within QGIS. Processes layers loaded in your QGIS project using calculated fields, geometry expressions, coordinate transformations, and database integration.

### Current State (v2.1.0)

The plugin processes layers from your QGIS project. Components include data reading, attribute transformation, geometry manipulation, coordinate reprojection, and export functionality.

Supports 15+ vector formats: Shapefile, GeoJSON, GeoPackage, KML, DXF, GPX, CSV, etc.

## Components

- **Layer Reader**: Access to QGIS project layers
- **Field Calculator**: QGIS expressions for field calculations and geometric operations
- **Geometry Transform**: Geometry manipulation via expressions (centroid, buffer, simplify)
- **Coordinate Transform**: CRS transformations using QGIS engine
- **Smart Filter**: Expression-based filtering with templates
- **Configuration Manager**: JSON-based config storage with bidirectional sync
- **Output**: Memory layers added to QGIS project
- **Logging**: Color-coded activity log with filtering

## Version History

### v2.1.0 (2025-12-12)
- Bidirectional sync between Configuration Preview and Field Management
- Validation errors display available source fields
- Fixed dict/string handling in clear_all_fields

### v2.0.0 (2025-12-01)
- Complete UI overhaul with EnhancedTransformerDialog
- Modular dock-based interface with layout presets
- Smart filter widget with expression templates
- Geometry transformation via expressions
- Activity log with color-coded filtering
- Keyboard shortcuts (Ctrl+1-4)
- PostgreSQL auto-mapping after transformation

### v1.x
- Initial releases with core transformation functionality
- QGIS project layer support
- Universal vector format support (15+ formats)
- PostgreSQL integration

## Planned Features (Roadmap)

### Reader Modes (Not Yet Implemented)
Write modes for PostgreSQL and file outputs:
- **APPEND**: Add features to existing layer/table
- **UPDATE**: Update existing features by key field match
- **REPLACE**: Drop and recreate layer/table

## Features

### Layer Processing

* Process QGIS project layers
* Support for vector formats compatible with QGIS
* Coordinate system transformations
* Geometric operations using QGIS expressions
* Field calculations and data type handling
* Batch processing for multiple layers

### Export

* Export to shapefile, GeoJSON, CSV
* Multiple layer processing
* Consistent output structure
* Field mapping configuration

### PostgreSQL Integration

* Database connection management
* Auto-mapping after transformations
* Field matching between layers and tables
* Manual mapping with type overrides
* Data type conversions

### Process Recording and Automation

* Record complete transformation workflows including filters, calculations, and coordinate systems
* Save processes as JSON templates for reuse across different layers
* Auto-load recorded processes when compatible layers are detected
* Share transformation workflows between users and projects
* Replay complex multi-step operations with one click
* Bidirectional field-expression synchronization

## Use Cases

Use cases:

* Record and replay transformation workflows for consistent processing
* Transform QGIS project layers with calculated fields and coordinate operations
* Automate repetitive tasks by saving complete process templates
* Share standardized transformation workflows across teams
* Integrate QGIS layers with PostgreSQL databases using recorded mappings
* Apply identical processing to multiple similar layers

## Technical Requirements

* **QGIS**: Version 3.28 or higher
* **Python**: 3.9+ (included with QGIS)
* **System**: Windows, macOS, Linux
* **PostgreSQL**: Optional, for database integration

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
├── __init__.py                                  # Plugin initialization
├── main_plugin.py                              # Main plugin class and QGIS integration
├── EnhancedTransformerDialog.py                 # Main enhanced interface dialog
├── Transformer_dialog.py                       # Core dialog functionality
├── AdvancedExpressionWidget.py                 # Expression builder component
├── SmartFilterWidget.py                        # Smart filtering component
├── FieldWidget.py                             # Field management component
├── ExpressionTesterDialog.py                   # Expression testing dialog
├── ExpressionSyntaxHighlighter.py             # Syntax highlighting for expressions
├── FieldDefinitionDialog.py                    # Field definition dialog
├── PreferencesDialog.py                        # User preferences dialog
├── config_selector.py                          # Configuration selection utilities
├── gestionnaire.py                             # Configuration manager
├── trans_calc.py                               # Transformation calculation engine
├── export_module.py                            # Export functionality module
├── postgresql_integration.py                   # PostgreSQL database integration
├── logger.py                                   # Logging system
├── styles.css                                  # UI styling
├── metadata.txt                                # Plugin metadata
├── calculated_fields_config.json               # Calculated fields configuration
├── postgresql_detailed_mappings.json           # PostgreSQL detailed mappings
├── transformer_postgresql.json                 # PostgreSQL connection settings
├── transformer_postgresql_mappings.json        # PostgreSQL table mappings
├── transformer_postgresql_preferences.json     # PostgreSQL preferences
└── README.md                                   # Documentation
```

## Usage Guide

### 1. Plugin Access

* **Menu**: `Extensions > Shape Transformer`
* **Toolbar**: Click the plugin icon
* **Vector Menu**: `Vector > Shape Transformer`

### 2. Main Interface

The interface consists of three main panels:

#### Left Panel - QGIS Layer Management

* **Show QGIS Layers**: Toggle to display all vector layers from your QGIS project
* **Layer List**: Display QGIS layers with visual differentiation (blue for QGIS layers)
* **Layer Management**: Select, filter, and manage layers directly from QGIS project
* **Auto-detection**: Automatically loads compatible configurations for known layers

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

#### Step 1: Access QGIS Layers

```
1. Load vector layers in your QGIS project
2. Toggle "Show QGIS Layers" in the plugin interface
3. Layers appear with visual differentiation and metadata
4. Compatible configurations auto-load for recognized layers
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
**Version**: 2.1.0
**License**: Open Source
**Repository**: https://github.com/yadda07/transformer

For technical support, please include:

- QGIS version used
- Problem description
- JSON configuration file (if applicable)
- Error messages from Log Panel

## Contributing

Contributions are welcome. Please contact the development team for information about contributing to the project.
