spiffy_theme_backend
====================
* The ultimate Odoo Backend theme with the most advanced key features of all time. Get your own personalized view while working on the Backend system with a wide range of choices. Spiffy theme has 3 in 1 Theme Style, Progressive Web App, Fully Responsive for all apps, Configurable Apps Icon, App Drawer with global search, RTL & Multi-Language Support, and many other key features.

Copyright and License
---------------------
* Copyright Bizople Solutions Pvt. Ltd.

Configuration
-------------
* For the search functionality with records search user need to first create records in Global search menu which located in Settings > Spiffy Configuration > Global Search

Usage
-----
* T3476 - PRR:
    - Updated request.session.pre_uid -> request.session.get('pre_uid') to fix login issue on the mobile app side.
    - Fixed sticky list view issue.  
    - Fixed overlapping list view header in the Expense module.
    - Fixed design issue occurring when attachment files were added in list view
    - Replaced ListRenderer XML file to fix columnWidths issue in list view  
* T4010 - PRR:
    - Fix the App menu icon issue 
    - Fix the error on menu click 
    - Fix app menu shape style design issue for menu list and fav apps
    - Added a condition so that the arrow is shown only if the menu has child menus. 
    - Fixed the padding for the top menu in the vertical header. 
* T4164 - PRR:
    - Changed leaveDuration in LoadingIndicator. 
    - Added a new registry in commandProviderRegistry for global record search.
    - Changed action in find_or_start_menu_record_search to open records dynamically without a full page reload.
    - Cleaned unused JS and xml code related to old implementation
* T6685 - VAA:
    - Change the default domain in column search

Changelog
---------
08-09-2025 - T3476 - PRR - Test and Fix Functionality & Design Issues in Spiffy Community v19
24-10-2025 - T4010 - PRR - Check & Fix Menu Icon issue and  Responsive design in theme backend (Community & Enterprise V19)
17-11-2025 - T4164 - PRR - Update Global Search Functionality in Spiffy Theme (Version 19)
18-11-2025 - T4164 - PRR - Update Global Search Functionality in Spiffy Theme (Version 19)
24-06-2026 - T6685 - VAA - Change the default domain in column search