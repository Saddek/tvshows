!function ($) {
  "use strict";
  
  function setupButtons(context) {
    $('.btn[data-action="seen"]', context).click(function() {
      var button = $(this);

      if (button.hasClass('disabled')) {
        return;
      }

      var div = button.closest('div[data-show-id]');
      var showId = div.data('showId');
      var episodeId = button.closest('*[data-episode-id]').data('episodeId');

      if (!showId || !episodeId) {
        throw new Error('No show and/or episode ID found');
      }

      button.find('> i').removeClass('icon-eye-open').addClass('icon-loader');
      button.addClass('disabled');

      $.getJSON(SCRIPT_ROOT + '/ajax/unseen/' + showId + '/' + episodeId, function(data, status, xhr) {
        if (xhr.status === 200) {
          if (div.attr('id') == 'showdetails') {
            // if we're in the show details page, just reset the button and update which row has the "muted" class (seen episodes)
            button.find('> i').removeClass('icon-loader').addClass('icon-eye-open');
            button.removeClass('disabled');
            
            $('tr[data-episode-id]').each(function (index, element) {
              if ($(this).data('episodeId') <= episodeId) {
                $(this).addClass('muted');
              } else {
                $(this).removeClass('muted');
              }
            });
          } else {
            // else we're on the front page, update the div's content with the one sent by the server
            div.html(data.unseen);

            // setup the buttons again, or they won't be clickable
            setupButtons(div);

            // update the upcoming episodes table
            $('table#upcoming').html(data.upcoming);
          }
        }
      }).error(function () {
        button.find('> i').removeClass('icon-loader').addClass('icon-eye-open');
        button.removeClass('disabled');
      });
    });

    $('a[data-action="more"]', context).click(function() {
      var button = $(this);

      var div = button.closest('div[data-show-id]');
      var showId = div.data('showId');

      if (!showId) {
        throw new Error('No show ID found');
      }

      // we backup the link before replacing it with the loader to put it back in case there is an error
      var backup = button.clone(true, true);

      var loader = $('<i class="icon-loader"></i>');
      button.replaceWith(loader);

      $.getJSON(SCRIPT_ROOT + '/ajax/more/' + showId + '/' + button.data('mult'), function(data, status, xhr) {
        if (xhr.status === 200) {
          // update the div's content with the one sent by the server
          div.html(data.unseen);

          // setup the buttons again, or they won't be clickable
          setupButtons(div);
        }
      }).error(function () {
        loader.replaceWith(backup);
      });
    });
  }

  setupButtons();

  $('.sortable').sortable().bind('sortupdate', function() {
    var ordering = {};
    
    $(this).find('> li[data-show-id]').each(function (index, element) {
      ordering[$(element).data('showId')] = index;
    });

    $.post('/ajax/showsorder', ordering);
  });

  $('#searchModal').on('show', function () {
    $('#search-results').html('<p class="lead">' + $('#search-results').data('placeholderText') + '</p>');
    $('#search-form input').val('');
    $('body').css('overflow', 'hidden');
  });

  $('#searchModal').on('shown', function () {
    $('#search-form input').focus();
  });

  $('#searchModal').on('hide', function () {
    $('body').css('overflow', 'auto');
  });

  $('#search-form').submit(function() {
    if (!$('#search-query').val()) return false; // don't search if the field is empty

    $('#search-results').html('<div class="progress progress-striped active"><div class="bar" style="width: 100%;"></div></div>');
    $('#search-results').load(SCRIPT_ROOT + '/ajax/search/' + encodeURIComponent($('#search-query').val()), function(response, textStatus, xhr) {
      if (xhr.status != 200) {
        $('#search-results').html('<p class="lead">' + $('#search-results').data('errorText') + '</p>');
      } else {
        $('#search-results a').click(function() {
          if ($(this).hasClass('disabled')) {
            return false;
          }

          $('#search-results a').addClass('disabled');
        });
      }
    });

    return false;
  });
}(window.jQuery);
