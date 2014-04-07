function VentureViewer(mapId, id){
    var prevBounds;
    var markers = {};
    var markerListeners = {};
    var postCache = {};
    var geocoder = new google.maps.Geocoder();
    var map;
    var city;
    var state;
    var category;
    var aggregatedPrices;
    var listId = 0;

    var minPriceFilter = 0;
    var maxPriceFilter = 0;  // 0 = no maximum
    var freshnessFilter = 48; // Hours 

    var windowFlag = false;

    var listFilters = {};
    var currentFilter;
    var circleOverlay, circleCenter;

    var viewMode = 'list';

    this.changeList = changeList;
    this.streetView = streetView;
    this.setFilter = setFilter;
    this.setViewMode = setViewMode;

    initializeControls();
    changeList(id);
   
    function initMap(location, zoom){
        if (map === undefined || map === null){
            if (location){
                var mapOptions = {
                    zoom: zoom,
                    center: location,
                    mapTypeId: google.maps.MapTypeId.ROADMAP,
                    streetViewControl: true,
                    panControlOptions: {
                        'position': google.maps.ControlPosition.LEFT_CENTER},
                    zoomControlOptions: {
                        'position': google.maps.ControlPosition.LEFT_CENTER}
                };

                map = new google.maps.Map($("#" + mapId).get(0),
                        mapOptions);

                google.maps.event.addListener(map, 'idle',
                        onBoundsChanged);
                google.maps.event.addListener(map, 'rightclick',
                        onRightClick);
            }
        }
        else{
            map.setCenter(location);
            map.setZoom(9);
        }
    }

    function setFilter(filter){
        currentFilter = filter;
        if (currentFilter.center != null && currentFilter.id){
            updateFilterLocation(currentFilter.center,
                    currentFilter.streetName);
        }
    }

    function setViewMode(mode){
        if (viewMode !== mode){
            viewMode = mode;
            clearCache();

            if (viewMode == 'list' && circleOverlay && circleCenter){
                circleOverlay.setMap(null);
                circleCenter.setMap(null);
            }
            else {
                if (currentFilter && currentFilter.center != null 
                        && currentFilter.id){
                    updateFilterLocation(currentFilter.center,
                            currentFilter.streetName);
                    confirmFilterLocation();
                }
            }
        }
    }

    function initiateFilterOverlay(){
        circleOverlay = new google.maps.Circle({
            'center': currentFilter.center,
            'radius': currentFilter.radius,
            'fillColor': '#336699',
            'fillOpacity': 0.5,
            'strokeColor': '#224466',
            'strokeOpacity': 0.6,
            'strokeWeight': 2
        });
        circleOverlay.setMap(map);
        google.maps.event.addListener(circleOverlay, 'rightclick',
                onRightClick);

        circleCenter = new google.maps.Marker({
            draggable: true,
            map: map,
            position: currentFilter.center,
            title: "Filter center @ " + currentFilter.streetName
        });

        google.maps.event.addListener(circleCenter, 'drag',
            function(e){
                circleOverlay.setCenter(e.latLng);
            }
        );

        google.maps.event.addListener(circleCenter, 'dragend',
            function(e){
                onRightClick(e);
            }
        );
    }

    function updateFilterLocation(location, streetName){
        if (location){
            currentFilter.center = location;
            currentFilter.streetName = streetName;

            $("#filter_center").val(streetName);


            // Update circle overlay
            if (circleOverlay !== undefined && circleOverlay !== null){
                circleCenter.setPosition(currentFilter.center);
                circleOverlay.setCenter(currentFilter.center);
                circleOverlay.setRadius(currentFilter.radius);
            }
            else {
                initiateFilterOverlay();
            }
        }
    }

    function confirmFilterLocation(){
        if (circleOverlay){
            var circleBounds = circleOverlay.getBounds();
            map.fitBounds(circleBounds);

            // Approximate "proximity" search.
            var ne = circleBounds.getNorthEast();
            var sw = circleBounds.getSouthWest();
            $.get('/services/bound/',
                {'north': ne.lat(), 'east': ne.lng(), 
                 'south': sw.lat(), 'west': sw.lng(),
                 'list': listId, 
                 'max_results': 25,
                }, function(response){
                    if (response.status == 'OK'){
                        updateMarkers(response.results);
                    }
                });
        }
    }

    function loadFilters(){
        listFilters = {};
        var filter;

        $("#filter_assoc_list").text("Filters @ " + city + "/" + category);
        $.get("/services/filter/", {list: listId},
            function(response){
                if (response.status == 'OK'){
                    $("#filter_list").empty().append(
                        '<option value="0">--SELECT A FILTER--</option>');

                    for (var i = 0; i < response.filters.length; ++i){
                        filter = response.filters[i];
                        listFilters[filter.id] = filter;

                        $("#filter_list").append('<option value="' + 
                            filter.id + '">' + filter.street.substr(0, 20) +
                            '...' + '</option>');
                    }

                    if (currentFilter){
                        $.each($("#filter_list option"),
                            function(idx, opt){
                                if (opt.value == currentFilter.id){
                                    $(opt).attr("selected", 'selected');
                                }
                            }
                        );
                        $("#filter_list").fadeOut('slow', function(){
                            $("#filter_list").show()});
                    }
                }
        });
    }

    function saveFilter(){
        if (currentFilter != null && currentFilter.center != null){
            $.post("/services/filter/", {
                list: listId,
                id: currentFilter.id,
                lat: currentFilter.center.lat(),
                lng: currentFilter.center.lng(),
                street: currentFilter.streetName,
                radius: currentFilter.radius,
                maxprice: currentFilter.maxPrice
            }, function(response){
                if (response.status == "OK"){
                    if (!currentFilter.id){
                        currentFilter.id = response.id;
                    }

                    loadFilters();
                }
            });
        }
    }

    function geoDecode(request, callback){
        var location = null;
        var address = null;
        geocoder.geocode(
            request,
            function(results, status){
                if (status == google.maps.GeocoderStatus.OK) {
                    location = results[0].geometry.location;
                    address = results[0].formatted_address;
                }
                else {
                    location = null;
                    address = null;
                }

                callback(location, address);
            });
    }

    function initializeControls(){
        $("#date_slider").slider({
            value: 38,
            min: 13,
            max: 100,
            slide: function(event, ui){
                var hoursBack = Math.round(Math.pow(ui.value/100*12.96, 2));
                if (hoursBack > 24){
                    $("#date_back_to").val(
                        Math.floor(hoursBack/24) + ' day(s)');
                }
                else{
                    $("#date_back_to").val(
                        hoursBack.toString() + ' hours');
                }
            },
            stop: function(event, ui){
                var hoursBack = Math.round(Math.pow(ui.value/100*12.96, 2));
                if (hoursBack > 24){
                    hoursBack = Math.floor(hoursBack/24) * 24;
                }
                freshnessFilter = hoursBack;
                onBoundsChanged();
            }
        });

        $("#radius_slider").slider({
            value: 2500,
            min: 500,
            max: 10000,
            slide: function(event, ui){
                var km_radius = ui.value / 1000;
                $("#filter_radius").val(km_radius.toFixed(1) + ' km');

                if (currentFilter != null){
                    currentFilter.radius = ui.value;
                    if (circleOverlay){
                        circleOverlay.setRadius(ui.value);
                    }
                }
            },
            stop: function(event, ui){
                if (circleOverlay){
                    confirmFilterLocation();
                }
            }
        });

        $("#set_center").click(function(e){
            geoDecode({address: $("#filter_center").val()},
                function(location, streetName){
                    if (location && currentFilter != null){
                        updateFilterLocation(location, streetName);
                        confirmFilterLocation();
                    }
                }
            );
        });

        $("#save_filter").click(function(e){
            saveFilter();
        });

        $("#filter_list").change(function(){
            var filter = listFilters[$("#filter_list").val()];
            if (filter !== undefined){
                currentFilter = {
                    id: filter.id,
                    streetName: filter.street,
                    radius: filter.radius,
                    center: new google.maps.LatLng(filter.center[0], 
                        filter.center[1]),
                    maxPrice: filter.maxPrice
                };

                var km_radius = filter.radius/1000;
                $("#filter_center").val(filter.street);
                $("#radius_slider").slider('value', filter.radius);
                $("#filter_radius").val(km_radius.toFixed(1) + ' km');
                $("#filter_max_price").val('$' + filter.maxPrice);
                $("#filter_price_slider").slider('value', filter.maxPrice);

                $("#filter_menu").hide('fast', 
                    function(){$(this).show('slow');});

                updateFilterLocation(currentFilter.center, 
                    currentFilter.streetName);
                confirmFilterLocation();
            }
        });
    }

    function changeList(lid){
        if (lid === 0 || lid === null){
            geoDecode({address: 'united states'}, 
                    function(location) {
                        initMap(location, 4);
                    });
            return;
        }

        if (listId != lid){
            listId = lid;
            clearCache();

            $.post('/services/pack/',
                {'kind': 'List', 'id': listId},
                function(response){
                    if (response.status == 'OK'){
                        city = response.List.city;
                        state = response.List.state;
                        category = response.List.category;
                        aggregatedPrices = response.List.aggregated_prices;

                        geoDecode({address: city + ' ' + state}, 
                            function(location, street) {
                                initMap(location, 9);
                            });

                        var cappedPrice = aggregatedPrices[2] * 3;

                        // Initialize price range slider
                        $("#price_slider").slider({
                            min: 0,
                            max: cappedPrice,
                            value: cappedPrice,
                            slide: function(event, ui){
                                $("#price_amount").val(
                                    "$" + ui.value);
                            },
                            stop: function(event, ui){
                                maxPriceFilter = ui.value;
                                onBoundsChanged();
                            },
                            create: function(event, ui){
                                $("#price_amount").val("$" +
                                    cappedPrice);
                            }
                        });
                        
                        $("#filter_price_slider").slider({
                            min: 0,
                            max: cappedPrice,
                            value: cappedPrice,
                            slide: function(event, ui){
                                $("#filter_max_price").val(
                                    '$' + ui.value);
                            },
                            stop: function(event, ui){
                                if (currentFilter != null){
                                    currentFilter.maxPrice = ui.value;
                                }
                            },
                            create: function(event, ui){
                                $("#filter_max_price").val(
                                    '$' + cappedPrice);
                            }
                        });

                        // Retrieve filters
                        loadFilters();
                    }
                }
            );
        }
    }

    function clearCache(){
        /* Clear markers and listeners */
        for (var id in markerListeners){
            if (markerListeners.hasOwnProperty(id)){
                google.maps.event.removeListener(markerListeners[id]);
            }
        }
        for (var id in markers){
            if (markers.hasOwnProperty(id)){
                markers[id].setMap(null);
            }
        }

        markers = {};
        markerListeners = {};
    }

    function updateMarkers(posts){
        clearCache();
        function _callback(assocId){
            return function(){
                windowFlag = true;
                loadPost(this, assocId);
            }
        }

        var now = Date.now();
        for (var i = 0; i < posts.length; ++i){
            var post = posts[i];

            // FIXME: A better way to deal with this?
            // We can filter within local results without a new request to
            // server side.
            if (viewMode == 'list' && maxPriceFilter > 0 &&
                    post.price > maxPriceFilter) continue;
            
            if (viewMode == 'filter' && currentFilter &&
                    currentFilter.maxPrice > 0 && 
                    post.price > currentFilter.maxPrice) continue;

            var markerLoc = new google.maps.LatLng(
                post.location[0],
                post.location[1]
            );
            var created = Date.parse(post.created);
            var priceTag = '';
            if (post.price < aggregatedPrices[1]){
                priceTag = 'green';
            }
            else if (post.price > aggregatedPrices[2]){
                priceTag = 'red';
            }
            else {
                priceTag = 'yellow';
            }

            var daysElapsed = Math.round((now - created) / 1000 / 3600 / 24);
            var markerUrl = '/static/icons/' + priceTag + '0' + 
                daysElapsed + '.png';

            var marker = new google.maps.Marker({
                draggable: true,
                position: markerLoc,
                icon: markerUrl,
                map: map,
                title: post.title
            });
            markers[post.id] = marker;

            var eventCallback = _callback(post.id);
            var listener = google.maps.event.addListener(marker,
                'click',
                eventCallback
            );
            markerListeners[post.id] = listener;
        }
    }

    function loadPost(marker, id){
        $.get("/services/post/", {'id': id},
            function(response){
                if (response.status == 'OK'){
                    var postDetail = '<h4><a target="_blank" href="' + 
                        response.post.link + '">' + response.post.title +
                        '</a> / <a href="javascript:void(0);" onclick="' + 
                        'streetView(' + id + ')">&raquo; Street View</a>' + 
                        '</h4><div><p>' + response.post.description + '</p><p>';

                    for (var i = 0; i < response.post.images.length; ++i){
                        postDetail += '<img src="' + 
                            response.post.images[i] + '" />';
                    }
                    postDetail += '</p></div>';

                    $("#post_dialog").html(postDetail);

                    var screenHeight = window.screen.availHeight;
                    var screenWidth = window.screen.availWidth;
                    $( "#post_dialog" ).dialog({
                        height: Math.floor(screenHeight * 0.6),
                        width: Math.floor(screenWidth * 0.6),
                        title: response.post.title,
                        modal: true
                    });
                }
            }
        );
    }

    function streetView(id){
        $( "#post_dialog" ).dialog("close");

        var markerLoc = markers[id].getPosition();
        var panorama = new google.maps.StreetViewPanorama(
            $("#" + mapId).get(0), {
                position: markerLoc,
                enableCloseButton: true,
            });

        panorama.setVisible(true);

    }

    /* Event handlers */
    function onRightClick(e){
        if (currentFilter !== undefined && currentFilter !== null){
            geoDecode(
                {location: e.latLng},
                function(location, streetName){
                    updateFilterLocation(location, streetName);
                    confirmFilterLocation();
                }
            );
        }
    }

    function onBoundsChanged(){
        if (windowFlag || listId == 0 || viewMode !== 'list'){
            windowFlag = false;
            return;
        }

        var currentBounds = map.getBounds();
        var ne = currentBounds.getNorthEast();
        var sw = currentBounds.getSouthWest();
        $.get('/services/bound/',
            {'north': ne.lat(), 'east': ne.lng(), 
             'south': sw.lat(), 'west': sw.lng(),
             'list': listId, 
             'max_results': map.getZoom() * 4,
             'freshness': freshnessFilter
            }, function(response){
                if (response.status == 'OK'){
                    updateMarkers(response.results);
                }
            });
        prevBounds = currentBounds;
    }
}

/* Utils */
function subscribe(){
    var city = $("#list_city").val();
    var state = $("#list_state").val();
    var category = $("#list_category").val();
    if (!city || !category){
        return false;
    }
    
    $.post('/services/subscribe/', 
        {'city': city, 'state': state, 'category': category},
        function(response){
            if (response.status == 'OK'){
                $("#sublist").append('<option value="' + response.list.id + 
                    '">' + response.list.city + '/' + response.list.category + 
                    '</option>');

                $("#list_city").val('');
                $("#list_state").val('');
                $("#subscribe_form").toggleClass('hidden');
            }
        }
    );
}

function streetView(id){
    ventureViewer.streetView(id);
}

/* Init */
var ventureViewer;
$(document).ready(function(){
    // Initiailizing interactive controls.
    $("#tabs").tabs({
        select: function(event, ui){
            if (ui.panel.id == 'filter_tab'){
                ventureViewer.setViewMode('filter');
            }
            else{
                ventureViewer.setViewMode('list');
            }
        }
    });

    $("#tools a").click(function(){
        $("#user_panel").fadeToggle('slow');
    });

    $("a.clickable").button();

    $("#add_filter").click(function(e){
        $("#filter_radius").val("2.5 km");
        $("#filter_center").val('');
        $("#radius_slider").slider('value', 2500);
        $("#filter_menu").hide('fast', function(){$(this).show('slow');});

        var filter = {
            id: 0,
            center: null,
            radius: 2500,
            maxPrice: 0
        };
        ventureViewer.setFilter(filter);
    });

    var activeListId = parseInt($("#sublist").val());
    if (!activeListId){
        ventureViewer = new VentureViewer("map_canvas", null);
    }
    else {
        ventureViewer = new VentureViewer("map_canvas", activeListId);
    }
});

